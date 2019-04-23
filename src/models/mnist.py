from src.models.pytorch import SPNClipper
import logging
from torch.nn import functional as F
import torch
from typing import Tuple
from torch import nn

# Create logger
logger = logging.getLogger(__name__)


def get_n_samples_from_loader(loader) -> int:
    """
    Get the number of samples in the data loader.
    Respects if the data loader has a sampler.


    Args:
        loader: Data loader.

    Returns:
        int: Number of samples in that data loader.
    """
    n_samples = len(loader.dataset)

    # If sampler is set, use the size of the sampler
    if loader.sampler:
        n_samples = len(loader.sampler)

    return n_samples


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
    clipper = SPNClipper(device)

    n_samples = get_n_samples_from_loader(train_loader)

    for batch_idx, (data, target) in enumerate(train_loader):
        import ipdb

        ipdb.set_trace(context=5)
        data, target = data.to(device), target.to(device)
        optimizer.zero_grad()
        output = model(data)
        loss = F.binary_cross_entropy(output, target.long())
        loss.backward()
        optimizer.step()
        model.apply(clipper)
        if batch_idx % log_interval == 0:
            logger.info(
                "Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}".format(
                    epoch,
                    batch_idx * len(data),
                    n_samples,
                    100.0 * batch_idx / len(train_loader),
                    loss.item(),
                )
            )


def train(model, device, train_loader, optimizer, epoch, log_interval=10):
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
    clipper = SPNClipper(device)

    n_samples = get_n_samples_from_loader(train_loader)

    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(device), target.to(device)
        optimizer.zero_grad()
        output = model(data)
        loss = F.nll_loss(output, target.long())
        loss.backward()
        optimizer.step()
        model.apply(clipper)
        if batch_idx % log_interval == 0:
            logger.info(
                "Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}".format(
                    epoch,
                    batch_idx * len(data),
                    n_samples,
                    100.0 * batch_idx / len(train_loader),
                    loss.item(),
                )
            )


def evaluate_model(
    model: nn.Module, device: str, loader, tag: str
) -> Tuple[float, float]:
    """
    Evaluate the model.
    
    Args:
        model (nn.Module): Network model.
        device: Torch device to evaluate on.
        loader: Torch dataset loader.
        tag: Tag for logging (Train/Test).

    Returns:
        Tuple[float, float]: Tuple of (loss, accuracy).
    """
    model.eval()
    loss = 0
    correct = 0
    with torch.no_grad():
        for data, target in loader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            loss += F.nll_loss(
                output, target.long(), reduction="sum"
            ).item()  # sum up batch loss
            pred = output.argmax(
                dim=1, keepdim=True
            )  # get the index of the max log-probability
            correct += pred.long().eq(target.long().view_as(pred)).sum().item()

    n_samples = get_n_samples_from_loader(loader)

    loss /= n_samples
    accuracy = 100.0 * correct / n_samples

    logger.info(
        "{} set: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)".format(
            tag, loss, correct, n_samples, accuracy
        )
    )
    return (loss, accuracy)


def evaluate_model_multilabel(
    model: nn.Module, device: str, loader, tag: str
) -> Tuple[float, float]:
    """
    Evaluate the model.
    
    Args:
        model (nn.Module): Network model.
        device: Torch device to evaluate on.
        loader: Torch dataset loader.
        tag: Tag for logging (Train/Test).

    Returns:
        Tuple[float, float]: Tuple of (loss, accuracy).
    """
    model.eval()
    loss = 0
    correct = 0
    with torch.no_grad():
        for data, target in loader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            loss += F.nll_loss(
                output, target.long(), reduction="sum"
            ).item()  # sum up batch loss
            pred = output.argmax(
                dim=1, keepdim=True
            )  # get the index of the max log-probability
            correct += pred.long().eq(target.long().view_as(pred)).sum().item()

    n_samples = get_n_samples_from_loader(loader)

    loss /= n_samples
    accuracy = 100.0 * correct / n_samples

    logger.info(
        "{} set: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)".format(
            tag, loss, correct, n_samples, accuracy
        )
    )
    return (loss, accuracy)
