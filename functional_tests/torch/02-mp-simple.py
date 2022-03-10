# based on the following example: https://github.com/pytorch/examples/tree/main/mnist_hogwild
# see also: https://github.com/pytorch/examples/tree/main/distributed
import argparse
import os

import torch
import torch.optim as optim
import torch.nn as nn
import torch.nn.functional as F
import torch.multiprocessing as mp
from torchvision import datasets, transforms
import wandb

parser = argparse.ArgumentParser(description="PyTorch MNIST Example")
parser.add_argument(
    "--batch-size",
    type=int,
    default=64,
    metavar="N",
    help="input batch size for training (default: 64)",
)
parser.add_argument(
    "--epochs",
    type=int,
    default=2,
    metavar="N",
    help="number of epochs to train (default: 10)",
)
parser.add_argument(
    "--lr", type=float, default=0.01, metavar="LR", help="learning rate (default: 0.01)"
)
parser.add_argument(
    "--momentum",
    type=float,
    default=0.5,
    metavar="M",
    help="SGD momentum (default: 0.5)",
)
parser.add_argument(
    "--seed", type=int, default=1, metavar="S", help="random seed (default: 1)"
)
parser.add_argument(
    "--log-interval",
    type=int,
    default=10,
    metavar="N",
    help="how many batches to wait before logging training status",
)
parser.add_argument(
    "--num-processes",
    type=int,
    default=2,
    metavar="N",
    help="how many training processes to use (default: 2)",
)


def train(run, rank, args, model, device, dataset, dataloader_kwargs):
    torch.manual_seed(1 + rank)

    train_loader = torch.utils.data.DataLoader(dataset, **dataloader_kwargs)

    optimizer = optim.SGD(model.parameters(), lr=args.lr, momentum=args.momentum)
    run.define_metric(f"step_{os.getpid}")
    for epoch in range(1, args.epochs + 1):
        train_epoch(run, epoch, args, model, device, train_loader, optimizer)


def train_epoch(run, epoch, args, model, device, data_loader, optimizer):
    model.train()
    pid = os.getpid()
    for batch_idx, (data, target) in enumerate(data_loader):
        optimizer.zero_grad()
        output = model(data.to(device))
        loss = F.nll_loss(output, target.to(device))
        loss.backward()
        optimizer.step()
        if batch_idx % args.log_interval == 0:
            print(
                "{}\tTrain Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}".format(
                    pid,
                    epoch,
                    batch_idx * len(data),
                    len(data_loader.dataset),
                    100.0 * batch_idx / len(data_loader),
                    loss.item(),
                )
            )
            run.log({"loss": loss.item(), f"step_{pid}": batch_idx * len(data)})


class MyModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 10, kernel_size=5)
        self.conv2 = nn.Conv2d(10, 20, kernel_size=5)
        self.conv2_drop = nn.Dropout2d()
        self.fc1 = nn.Linear(320, 50)
        self.fc2 = nn.Linear(50, 10)

    def forward(self, x):
        x = F.relu(F.max_pool2d(self.conv1(x), 2))
        x = F.relu(F.max_pool2d(self.conv2_drop(self.conv2(x)), 2))
        x = x.view(-1, 320)
        x = F.relu(self.fc1(x))
        x = F.dropout(x, training=self.training)
        x = self.fc2(x)
        return F.log_softmax(x, dim=1)


if __name__ == "__main__":

    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    transform = transforms.Compose(
        [transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))]
    )
    dataset1 = datasets.MNIST("../data", train=True, download=True, transform=transform)
    # dataset2 = datasets.MNIST("../data", train=False, transform=transform)

    kwargs = {"batch_size": args.batch_size, "shuffle": True}

    model = MyModel().to(device)
    # NOTE: this is required for the ``fork`` method to work
    model.share_memory()

    torch.manual_seed(args.seed)
    mp.set_start_method("spawn")

    wandb.require("service")
    run = wandb.init()

    processes = []
    for rank in range(args.num_processes):
        p = mp.Process(
            target=train, args=(run, rank, args, model, device, dataset1, kwargs)
        )
        # We first train the model across `num_processes` processes
        p.start()
        processes.append(p)

    for p in processes:
        p.join()

    run.finish()
