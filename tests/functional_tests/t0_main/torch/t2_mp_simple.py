# based on: https://github.com/pytorch/examples/tree/main/mnist_hogwild
import os

import torch
import torch.multiprocessing as mp
import torch.nn as nn
import torch.nn.functional as F  # noqa: N812
import torch.optim as optim
import wandb
from PIL import Image
from torchvision import transforms

SEED = 1
BATCH_SIZE = 32
EPOCHS = 2
LOG_INTERVAL = 10


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


class MyDatatse(torch.utils.data.Dataset):
    def __init__(self, transform, size=BATCH_SIZE * LOG_INTERVAL * 5) -> None:
        self.data = torch.randint(0, 256, (size, 28, 28), dtype=torch.uint8)
        self.targets = torch.randint(0, 10, (size,))
        self.transform = transform

    def __getitem__(self, index: int):
        img, target = self.data[index], int(self.targets[index])

        img = Image.fromarray(img.numpy(), mode="L")

        if self.transform is not None:
            img = self.transform(img)

        return img, target

    def __len__(self) -> int:
        return len(self.data)


def train(run, rank, model, device, dataset):
    torch.manual_seed(SEED + rank)

    dataloader_kwargs = {"batch_size": BATCH_SIZE, "shuffle": True}
    train_loader = torch.utils.data.DataLoader(dataset, **dataloader_kwargs)

    optimizer = optim.SGD(model.parameters(), lr=0.01, momentum=0.5)
    run.define_metric(f"step_{os.getpid}")
    for epoch in range(1, EPOCHS + 1):
        train_epoch(run, epoch, model, device, train_loader, optimizer)


def train_epoch(run, epoch, model, device, data_loader, optimizer):
    model.train()
    pid = os.getpid()
    for batch_idx, (data, target) in enumerate(data_loader):
        optimizer.zero_grad()
        output = model(data.to(device))
        loss = F.nll_loss(output, target.to(device))
        loss.backward()
        optimizer.step()
        if batch_idx % LOG_INTERVAL == 0:
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


if __name__ == "__main__":

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = MyModel().to(device)
    # NOTE: this is required for the ``fork`` method to work
    model.share_memory()

    transform = transforms.Compose(
        [transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))]
    )

    dataset = MyDatatse(transform=transform)

    torch.manual_seed(SEED)
    mp.set_start_method("spawn")

    wandb.require("service")
    run = wandb.init()

    processes = []
    for rank in range(2):
        p = mp.Process(target=train, args=(run, rank, model, device, dataset))
        # We first train the model across `num_processes` processes
        p.start()
        processes.append(p)

    for p in processes:
        p.join()

    run.finish()
