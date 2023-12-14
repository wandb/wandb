import torch
import torch.nn as nn
import torch.nn.functional as F  # noqa N812
import wandb
from torch.utils.tensorboard import SummaryWriter


def main():
    wandb.init(tensorboard=True)

    class ConvNet(nn.Module):
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

    writer = SummaryWriter()
    net = ConvNet()
    wandb.watch(net, log_freq=2)
    for i in range(10):
        output = net(torch.ones((64, 1, 28, 28)))
        loss = F.mse_loss(output, torch.ones((64, 10)))
        output.backward(torch.ones(64, 10))
        writer.add_scalar("loss", loss / 64, i + 1)
        writer.add_image("example", torch.ones((1, 28, 28)), i + 1)
    writer.close()


if __name__ == "__main__":
    main()
