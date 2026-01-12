"""Test Metaflow Flow integration"""

from __future__ import annotations

import os
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F  # noqa: N812
import torch.optim as optim
import wandb
from metaflow import FlowSpec, Parameter, step
from torch.optim.lr_scheduler import StepLR
from torchvision import datasets, transforms
from wandb.integration.metaflow import wandb_log

os.environ["METAFLOW_USER"] = "test_user"
os.environ["USER"] = os.environ["METAFLOW_USER"]


@wandb_log
class WandbPyTorchFlow(FlowSpec):
    batch_size = Parameter("batch_size", default=64)
    test_batch_size = Parameter("test_batch_size", default=1000)
    epochs = Parameter("epochs", default=1)
    lr = Parameter("lr", default=1.0)
    gamma = Parameter("gamma", default=0.7)
    no_cuda = Parameter("no_cuda", default=False)
    seed = Parameter("seed", default=1)
    log_interval = Parameter("log_interval", default=10)
    save_model = Parameter("save_model", default=False)

    @wandb_log(datasets=True, models=True, others=True)
    @step
    def start(self):
        self.use_cuda = not self.no_cuda and torch.cuda.is_available()

        torch.manual_seed(self.seed)

        self.train_kwargs = {"batch_size": self.batch_size}
        self.test_kwargs = {"batch_size": self.test_batch_size}
        if self.use_cuda:
            self.cuda_kwargs = {"num_workers": 1, "pin_memory": True, "shuffle": True}
            self.train_kwargs.update(self.cuda_kwargs)
            self.test_kwargs.update(self.cuda_kwargs)

        self.mnist_dir = Path("../data")
        self.next(self.setup_data)

    @wandb_log(datasets=False, models=False, others=False)
    @step
    def setup_data(self):
        transform = transforms.Compose(
            [transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))]
        )
        self.dataset1 = datasets.FakeData(
            size=100,
            image_size=(1, 28, 28),
            num_classes=10,
            transform=transform,
        )
        self.dataset2 = datasets.FakeData(
            size=100,
            image_size=(1, 28, 28),
            num_classes=10,
            transform=transform,
        )
        self.next(self.setup_dataloaders)

    @step
    def setup_dataloaders(self):
        self.train_loader = torch.utils.data.DataLoader(
            self.dataset1, **self.train_kwargs
        )
        self.test_loader = torch.utils.data.DataLoader(
            self.dataset2, **self.test_kwargs
        )
        self.next(self.train_model)

    @step
    def train_model(self):
        torch.manual_seed(self.seed)
        device = torch.device("cuda" if self.use_cuda else "cpu")

        self.model = Net()
        self.model.to(device)
        optimizer = optim.Adadelta(self.model.parameters(), lr=self.lr)

        scheduler = StepLR(optimizer, step_size=1, gamma=self.gamma)
        for epoch in range(1, self.epochs + 1):
            train(
                self.model,
                device,
                self.train_loader,
                optimizer,
                epoch,
                self.log_interval,
            )
            test(self.model, device, self.test_loader)
            scheduler.step()

        if self.save_model:
            torch.save(self.model.state_dict(), "mnist_cnn.pt")

        self.next(self.end)

    @step
    def end(self):
        pass


# ADAPTED FROM PYTORCH MNIST DEMO


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(784, 10)

    def forward(self, x):
        x = torch.flatten(x, 1)
        x = self.fc(x)
        output = F.log_softmax(x, dim=1)
        return output


def train(model, device, train_loader, optimizer, epoch, log_interval):
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(device), target.to(device)
        optimizer.zero_grad()
        output = model(data)
        loss = F.nll_loss(output, target)
        loss.backward()
        optimizer.step()
        if batch_idx % log_interval == 0:
            wandb.log(
                {"epoch": epoch, "step": batch_idx * len(data), "loss": loss.item()}
            )


def test(model, device, test_loader):
    model.eval()
    test_loss = 0
    correct = 0
    with torch.no_grad():
        for data, target in test_loader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            test_loss += F.nll_loss(
                output, target, reduction="sum"
            ).item()  # sum up batch loss
            pred = output.argmax(
                dim=1, keepdim=True
            )  # get the index of the max log-probability
            correct += pred.eq(target.view_as(pred)).sum().item()

    test_loss /= len(test_loader.dataset)
    wandb.log({"test_loss": test_loss, "accuracy": correct / len(test_loader.dataset)})


if __name__ == "__main__":
    wandb.setup()
    WandbPyTorchFlow()
