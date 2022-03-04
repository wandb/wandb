import argparse
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import datasets, transforms
from torch.optim.lr_scheduler import StepLR
import math
device = torch.device("cpu")
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
def train(model, train_loader, optimizer, epoch):
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(device), target.to(device)
        optimizer.zero_grad()
        output = model(data)
        loss = F.nll_loss(output, target)
        loss.backward()
        optimizer.step()
        if batch_idx % 10 == 0:
            print(
                "Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}".format(
                    epoch,
                    batch_idx * len(data),
                    len(train_loader.dataset),
                    100.0 * batch_idx / len(train_loader),
                    loss.item(),
                )
            )
def evaluate_model(model, eval_data):
    model.eval()
    eval_loader = torch.utils.data.DataLoader(eval_data, batch_size=1000)
    test_loss = 0
    correct = 0
    preds = []
    with torch.no_grad():
        for data, target in eval_loader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            test_loss += F.nll_loss(
                output, target, reduction="sum"
            ).item()  # sum up batch loss
            pred = output.argmax(
                dim=1, keepdim=True
            )  # get the index of the max log-probability
            preds += list(pred.flatten().tolist())
            correct += pred.eq(target.view_as(pred)).sum().item()
    test_loss /= len(eval_loader.dataset)
    accuracy = 100.0 * correct / len(eval_loader.dataset)
    print(
        "\nTest set: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)\n".format(
            test_loss, correct, len(eval_loader.dataset), accuracy
        )
    )
    return test_loss, accuracy, preds
def seed(seed=1):
    torch.manual_seed(seed)
def load_training_data_split(train_count=1000, val_count=200):
    if train_count + val_count < 60000:
        extra = 60000 - train_count - val_count
    else:
        extra = 0
    train_data = datasets.MNIST(
        "./data", train=True, download=True, transform=_preprocessing_transformer()
    )
    t, v, e = torch.utils.data.random_split(train_data, [train_count, val_count, extra])
    return t, v
def build_model(lr=1.0):
    model = Net().to(device)
    optimizer = optim.Adadelta(model.parameters(), lr=lr)
    return model, optimizer
def train_model(
    model, optimizer, train_data, batch_size=64, gamma=0.7, epochs=14, onEpochEnd=None
):
    train_loader = torch.utils.data.DataLoader(train_data, batch_size=batch_size)
    scheduler = StepLR(optimizer, step_size=1, gamma=gamma)
    for epoch in range(1, epochs + 1):
        train(model, train_loader, optimizer, epoch)
        onEpochEnd(epoch, model)
        scheduler.step()
    return model
def load_test_data(test_size):
    extra = 10000 - test_size if test_size < 10000 else 0
    data = datasets.MNIST("./data", train=False, transform=_preprocessing_transformer())
    t, e = torch.utils.data.random_split(data, [test_size, extra])
    return t
def _preprocessing_transformer():
    return transforms.Compose(
        [transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))]
    )
