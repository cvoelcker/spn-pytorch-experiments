import os
import sys
import time
import logging
import torch
from typing import Tuple
import numpy as np

from torch import nn, optim
from torch.utils.tensorboard import SummaryWriter
from src.spn import distributions as spndist

from src.data.data import store_results
from src.data.data_loader import load_multi_mnist
from src.utils.utils import get_n_samples_from_loader
from src.utils.utils import set_cuda_device
from src.spn.clipper import DistributionClipper
from src.spn.clipper import SumWeightNormalizer
from src.spn.clipper import SumWeightClipper
from src.utils.args import init_argparser
from src.utils.args import save_args
from src.utils.utils import (
    count_params,
    set_seed,
    setup_logging,
    time_delta_now,
    collect_tensorboard_info,
)
from src.models.models import *
from src.models.models import get_model_by_tag

os.environ["OMP_NUM_THREADS"] = "1"


sys.path.insert(0, "./")


logger = logging.getLogger(__name__)


def parse_args():
    parser = init_argparser()

    # Specific arguments for this experiment
    parser.add_argument(
        "--n-labels",
        type=int,
        default=2,
        metavar="N",
        help="Number of labels for artificial multilabel mnist task. Digits will be sample from [0, 1, ..., n_labels]",
    )
    parser.add_argument(
        "--canvas-size", type=int, default=50, metavar="N", help="Canvas size."
    )
    parser.add_argument(
        "--n-digits",
        type=int,
        default=5,
        metavar="N",
        help="Number of maximum digits per canvas.",
    )
    args = parser.parse_args()

    if args.n_digits > args.n_labels:
        raise Exception("Option --n-digits has to be <= --n-labels.")
    return args


def evaluate_model_multilabel(
    model: nn.Module, device: str, loader, tag: str, n_labels: int
) -> Tuple[float, float]:
    """
    Evaluate the model.
    
    Args:
        model (nn.Module): Network model.
        device: Torch device to evaluate on.
        loader: Torch dataset loader.
        tag: Tag for logging (Train/Test).
        n_labels: Number of labels.

    Returns:
        Tuple[float, float]: Tuple of (loss, accuracy).
    """
    model.eval()

    loss = 0.0
    correct = 0

    loss_fn = nn.BCELoss(reduction="sum")

    # Collect targets and outputs
    with torch.no_grad():
        for data, target in loader:
            # Send data and target to correct device
            data, target = data.to(device), target.to(device)

            # Do inference
            output = model(data)

            # Comput loss
            loss += loss_fn(output, target)

            pred = output > 0.5
            correct += pred.long().eq(target.long().view_as(pred)).sum().item()

    n_samples = get_n_samples_from_loader(loader) * n_labels

    loss /= n_samples

    accuracy = 100.0 * correct / n_samples

    logger.info(
        "{: <5} set: Average loss: {:.4f}, Accuracy: {:.2f}%".format(
            tag, loss, accuracy
        )
    )
    return (loss, accuracy)


def train_multilabel(model, device, train_loader, optimizer, epoch, log_interval=10):
    """
    Train the model for one epoch.

    Args:
        model (nn.Module): Network model.
        device: Device to train on.
        train_loader: Torch data loader for training set.
        optimizer: Torch opitimizer.
        epoch: Current epoch.
    """

    model.train()

    # Create clipper
    dist_clipper = DistributionClipper(device)
    sum_weight_normalizer = SumWeightNormalizer()
    sum_weight_clipper = SumWeightClipper(device)

    n_samples = get_n_samples_from_loader(train_loader)
    loss_fn = nn.BCELoss()
    t_start = time.time()
    for batch_idx, (data, target) in enumerate(train_loader):
        # Send data to correct device
        data, target = data.to(device), target.to(device)

        # Reset gradients
        optimizer.zero_grad()

        # Inference
        output = model(data)

        # Comput loss
        loss = loss_fn(output, target)

        # Backprop
        loss.backward()
        optimizer.step()

        # Clip distribution values and weights
        model.apply(dist_clipper)
        model.apply(sum_weight_clipper)

        # Log stuff
        if batch_idx % log_interval == 0:
            logger.info(
                "Train Epoch: {} [{: >5}/{: <5} ({:.0f}%)]\tLoss: {:.6f}".format(
                    epoch,
                    batch_idx * len(data),
                    n_samples,
                    100.0 * batch_idx / len(train_loader),
                    loss.item(),
                )
            )
        # if batch_idx % log_interval * 3 == 0:
        #     logger.info("Samples:")
        #     logger.info("Target: %s", target[0].cpu().numpy())
        #     logger.info("Output: %s", output[0].detach().cpu().numpy())

    model.apply(sum_weight_normalizer)
    t_delta = time_delta_now(t_start)
    logger.info("Train Epoch: {} took {}".format(epoch, t_delta))


def run_multilabel_mnist(args, base_dir):
    """
    Run the multilabel mnist experiment with the given arguments.
    Args:
        args: Command line args.
        base_dir: Directory in which the experiment will be stored.

    """
    # Set seed globally
    set_seed(args.seed)
    use_cuda = args.cuda and torch.cuda.is_available()
    device = torch.device("cuda:{}".format(args.cuda_device_id) if use_cuda else "cpu")

    logger.info("Main device: %s", device)

    # Get the mnist loader
    train_loader, test_loader = load_multi_mnist(
        n_labels=args.n_labels, canvas_size=args.canvas_size, seed=args.seed, args=args
    )

    # Retreive model
    model = get_model_by_tag(
        args.net, device, args, args.canvas_size ** 2, args.n_labels
    )

    # Disable track_running_stats in batchnorm according to
    # https://discuss.pytorch.org/t/performance-highly-degraded-when-eval-is-activated-in-the-test-phase/3323/12
    for child in model.modules():
        if type(child) == nn.BatchNorm2d or type(child) == nn.BatchNorm1d:
            child.track_running_stats = False

    logger.info("Number of paramters: %s", count_params(model))

    # Define optimizer
    optimizer = optim.Adam(model.parameters(), lr=args.lr)

    # Scheduler for learning rate
    gamma = 0.5
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=10, gamma=gamma)

    writer = SummaryWriter(log_dir=os.path.join(base_dir, "tb-log"))

    data = []
    # Run epochs
    for epoch in range(1, args.epochs + 1):
        # Start counting after 10 epochs, that is, first lr reduction is at epoch 20
        if epoch > 10:
            logger.info(
                "Epoch %s: Reducing learning rate by %s to %s",
                epoch,
                gamma,
                optimizer.param_groups[0]["lr"],
            )
            scheduler.step()

        # Run train
        train_multilabel(
            model, device, train_loader, optimizer, epoch, args.log_interval
        )

        # Evaluate model on train/test data
        train_loss, train_acc = evaluate_model_multilabel(
            model, device, train_loader, "Train", args.n_labels
        )
        test_loss, test_acc = evaluate_model_multilabel(
            model, device, test_loader, "Test", args.n_labels
        )
        data.append([epoch, train_acc, test_acc, train_loss, test_loss])

        # Collect data
        collect_tensorboard_info(
            writer, model, epoch, train_acc, test_acc, train_loss, test_loss
        )

    column_names = ["epoch", "train_acc", "test_acc", "train_loss", "test_loss"]
    store_results(
        result_dir=base_dir, dataset_name="mnist", column_names=column_names, data=data
    )


def plot_sample(x, y, y_pred, loss):
    """
    Plot a single sample witht the target and prediction in the title.

    Args:
        x: Image.
        y: Target.
        y_pred: Target prediction.
        loss: Loss value.
    """
    import matplotlib.pyplot as plt

    plt.imshow(x.squeeze().numpy())
    plt.title(
        "y={}\ny_pred={}\nloss={}".format(
            y.squeeze().numpy(),
            y_pred.squeeze().detach().numpy(),
            loss.detach().numpy(),
        )
    )
    plt.show()
