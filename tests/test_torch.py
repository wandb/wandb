import torch
import torch.nn as nn
import torch.nn.functional as F
import wandb
from pprint import pprint
from torchvision import models


class Net(nn.Module):
    def __init__(self):
        super(Net, self).__init__()
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


def test_simple_net():
    net = Net()
    graph = wandb.Graph.hook_torch(net)
    output = net.forward(torch.ones((64, 1, 28, 28), requires_grad=True))
    grads = torch.ones(64, 10)
    output.backward(grads)
    graph = wandb.Graph.transform(graph)
    assert len(graph["nodes"]) == 5
    assert graph["nodes"][0]['class_name'] == "Conv2d(1, 10, kernel_size=(5, 5), stride=(1, 1))"
    assert graph["nodes"][0]['name'] == "conv1"


def test_alex_net():
    alex = models.AlexNet()
    graph = wandb.Graph.hook_torch(alex)
    output = alex.forward(torch.ones((2, 3, 224, 224), requires_grad=True))
    grads = torch.ones(2, 1000)
    output.backward(grads)
    graph = wandb.Graph.transform(graph)
    assert len(graph["nodes"]) == 20
    assert graph["nodes"][0]['class_name'] == "Conv2d(3, 64, kernel_size=(11, 11), stride=(4, 4), padding=(2, 2))"
    assert graph["nodes"][0]['name'] == "features.0"
