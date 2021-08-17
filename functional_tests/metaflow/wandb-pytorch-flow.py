"""
Test Metaflow Flow integration

---
id: metaflow.pytorch.base
plugin:
  - wandb
command:
    args:
        - --no-pylint
        - run
assert:
    - :wandb:runs_len: 5
    - :wandb:runs[0][config]: {"batch_size": 64, "test_batch_size": 1000, "epochs": 1, "lr": 1.0, "gamma": 0.7, "no_cuda": False, "dry_run": False, "seed": 1, "log_interval": 10, "save_model": False}
    - :wandb:runs[1][config]: {"batch_size": 64, "test_batch_size": 1000, "epochs": 1, "lr": 1.0, "gamma": 0.7, "no_cuda": False, "dry_run": False, "seed": 1, "log_interval": 10, "save_model": False}
    - :wandb:runs[2][config]: {"batch_size": 64, "test_batch_size": 1000, "epochs": 1, "lr": 1.0, "gamma": 0.7, "no_cuda": False, "dry_run": False, "seed": 1, "log_interval": 10, "save_model": False}
    - :wandb:runs[3][config]: {"batch_size": 64, "test_batch_size": 1000, "epochs": 1, "lr": 1.0, "gamma": 0.7, "no_cuda": False, "dry_run": False, "seed": 1, "log_interval": 10, "save_model": False}
    - :wandb:runs[4][config]: {"batch_size": 64, "test_batch_size": 1000, "epochs": 1, "lr": 1.0, "gamma": 0.7, "no_cuda": False, "dry_run": False, "seed": 1, "log_interval": 10, "save_model": False}
    - :wandb:runs[0][summary]: {"test_kwargs": {"batch_size": 1000}, "train_kwargs": {"batch_size": 64}, "use_cuda": False}
    - :wandb:runs[0][exitcode]: 0
    - :wandb:runs[1][exitcode]: 0
    - :wandb:runs[2][exitcode]: 0
    - :wandb:runs[3][exitcode]: 0
    - :wandb:runs[4][exitcode]: 0
"""

# Remove this because it's not consistent between environments...
# - :wandb:runs[3][summary]: {'epoch': 1, 'step': 1920, 'loss': 0.6059669852256775, 'test_loss': 0.44002601623535154, 'accuracy': 0.8585}


import os
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.optim.lr_scheduler import StepLR
from torchvision import datasets, transforms
from wandb.integration.metaflow import wandb_log

import wandb
from metaflow import FlowSpec, Parameter, step

os.environ["WANDB_SILENT"] = "true"
os.environ["METAFLOW_USER"] = "test_user"


@wandb_log
class WandbPyTorchFlow(FlowSpec):
    batch_size = Parameter("batch_size", default=64)
    test_batch_size = Parameter("test_batch_size", default=1000)
    epochs = Parameter("epochs", default=1)
    lr = Parameter("lr", default=1.0)
    gamma = Parameter("gamma", default=0.7)
    no_cuda = Parameter("no_cuda", default=False)
    dry_run = Parameter("dry_run", default=False)
    seed = Parameter("seed", default=1)
    log_interval = Parameter("log_interval", default=10)
    save_model = Parameter("save_model", default=False)

    @wandb_log(datasets=True, models=True, others=True)
    # @wandb_log(datasets=False, models=False, others=False)
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

    # @wandb_log(datasets=True, models=True, others=True)
    @wandb_log(datasets=False, models=False, others=False)
    @step
    def setup_data(self):
        transform = transforms.Compose(
            [transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))]
        )
        dataset1 = datasets.MNIST(
            self.mnist_dir, train=True, download=True, transform=transform
        )
        dataset2 = datasets.MNIST(self.mnist_dir, train=False, transform=transform)

        # this subset to speed up testing
        subset = torch.arange(2000)
        self.dataset1 = torch.utils.data.Subset(dataset1, subset)
        self.dataset2 = torch.utils.data.Subset(dataset2, subset)
        self.next(self.setup_dataloaders)

    # @wandb_log(datasets=True, models=True, others=True)
    # @wandb_log(datasets=False, models=False, others=False)
    @step
    def setup_dataloaders(self):
        self.train_loader = torch.utils.data.DataLoader(
            self.dataset1, **self.train_kwargs
        )
        self.test_loader = torch.utils.data.DataLoader(
            self.dataset2, **self.test_kwargs
        )
        self.next(self.train_model)

    # @wandb_log(datasets=True, models=True, others=True)
    # @wandb_log(datasets=False, models=False, others=False)
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
                self.dry_run,
            )
            test(self.model, device, self.test_loader)
            scheduler.step()

        if self.save_model:
            torch.save(self.model.state_dict(), "mnist_cnn.pt")

        self.next(self.end)

    # @wandb_log(datasets=True, models=True, others=True)
    # @wandb_log(datasets=False, models=False, others=False)
    @step
    def end(self):
        pass


# ADAPTED FROM PYTORCH MNIST DEMO


class Net(nn.Module):
    def __init__(self):
        super(Net, self).__init__()
        self.conv1 = nn.Conv2d(1, 32, 3, 1)
        self.conv2 = nn.Conv2d(32, 64, 3, 1)
        self.dropout1 = nn.Dropout(0.25)
        self.dropout2 = nn.Dropout(0.5)
        self.fc1 = nn.Linear(9216, 128)
        self.fc2 = nn.Linear(128, 10)

    def forward(self, x):
        x = self.conv1(x)
        x = F.relu(x)
        x = self.conv2(x)
        x = F.relu(x)
        x = F.max_pool2d(x, 2)
        x = self.dropout1(x)
        x = torch.flatten(x, 1)
        x = self.fc1(x)
        x = F.relu(x)
        x = self.dropout2(x)
        x = self.fc2(x)
        output = F.log_softmax(x, dim=1)
        return output


def train(model, device, train_loader, optimizer, epoch, log_interval, dry_run):
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
            if dry_run:
                break


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
    WandbPyTorchFlow()
