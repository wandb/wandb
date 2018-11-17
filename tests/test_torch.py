import torch
import torch.nn as nn
import torch.nn.functional as F
import wandb
from pprint import pprint
from torchvision import models
from torch.autograd import Variable



class ConvNet(nn.Module):
    def __init__(self):
        super(ConvNet, self).__init__()
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

class LSTMModel(torch.nn.Module):
    def __init__(self, embedding_dim, hidden_dim):
        super(LSTMModel, self).__init__()
        vocabLimit = 100
        self.hidden_dim = hidden_dim
        self.embeddings = nn.Embedding(vocabLimit + 1, embedding_dim)
        self.lstm = nn.LSTM(embedding_dim, hidden_dim)
        self.linearOut = nn.Linear(hidden_dim, 2)

    def forward(self, inputs, hidden):
        x = self.embeddings(inputs).view(len(inputs), 1, -1)
        lstm_out, lstm_h = self.lstm(x, hidden)
        x = lstm_out[-1]
        x = self.linearOut(x)
        x = F.log_softmax(x, dim=1)
        return x, lstm_h

    def init_hidden(self):
        return (
        Variable(torch.zeros(1, 1, self.hidden_dim)), Variable(torch.zeros(1, 1, self.hidden_dim)))

class Sequence(nn.Module):
    def __init__(self):
        super(Sequence, self).__init__()
        self.lstm1 = nn.LSTMCell(1, 51)
        self.lstm2 = nn.LSTMCell(51, 51)
        self.linear = nn.Linear(51, 1)

    def forward(self, input, future=0):
        outputs = []
        h_t = torch.zeros(input.size(0), 51, dtype=torch.double)
        c_t = torch.zeros(input.size(0), 51, dtype=torch.double)
        h_t2 = torch.zeros(input.size(0), 51, dtype=torch.double)
        c_t2 = torch.zeros(input.size(0), 51, dtype=torch.double)

        for i, input_t in enumerate(input.chunk(input.size(1), dim=1)):
            h_t, c_t = self.lstm1(input_t, (h_t, c_t))
            h_t2, c_t2 = self.lstm2(h_t, (h_t2, c_t2))
            output = self.linear(h_t2)
            outputs += [output]
        for i in range(future):  # if we should predict the future
            h_t, c_t = self.lstm1(output, (h_t, c_t))
            h_t2, c_t2 = self.lstm2(h_t, (h_t2, c_t2))
            output = self.linear(h_t2)
            outputs += [output]
        outputs = torch.stack(outputs, 1).squeeze(2)
        return outputs


def test_no_requires_grad(history):
    # log_stats() used to fail on tensors that didn't have .require_grad = True
    history.torch.log_stats(torch.randn(3, 3))
    history.torch.log_stats(torch.autograd.Variable(torch.randn(3, 3)))


def test_simple_net():
    net = ConvNet()
    graph = wandb.Graph.hook_torch(net)
    output = net.forward(torch.ones((64, 1, 28, 28), requires_grad=True))
    grads = torch.ones(64, 10)
    output.backward(grads)
    graph = wandb.Graph.transform(graph)
    assert len(graph["nodes"]) == 5
    assert graph["nodes"][0]['class_name'] == "Conv2d(1, 10, kernel_size=(5, 5), stride=(1, 1))"
    assert graph["nodes"][0]['name'] == "conv1"


def test_sequence_net():
    net = Sequence()
    net.double()
    graph = wandb.Graph.hook_torch(net)
    output = net.forward(torch.ones(
        (97, 999), requires_grad=True, dtype=torch.double))
    output.backward(torch.zeros((97, 999), dtype=torch.double))
    graph = wandb.Graph.transform(graph)
    pprint(graph)
    assert len(graph["nodes"]) == 3
    assert len(graph["nodes"][0]['parameters']) == 4
    assert graph["nodes"][0]['class_name'] == "LSTMCell(1, 51)"
    assert graph["nodes"][0]['name'] == "lstm1"


def test_multi_net():
    net = ConvNet()
    wandb.run = wandb.wandb_run.Run.from_environment_or_defaults()
    graphs = wandb.hook_torch((net, net))
    wandb.run = None
    output = net.forward(torch.ones((64, 1, 28, 28), requires_grad=True))
    grads = torch.ones(64, 10)
    output.backward(grads)
    graph1 = wandb.Graph.transform(graphs[0])
    graph2 = wandb.Graph.transform(graphs[1])
    assert len(graph1["nodes"]) == 5
    assert len(graph2["nodes"]) == 5


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

def test_lstm():
    net = LSTMModel(2,2)
    wandb.run = wandb.wandb_run.Run.from_environment_or_defaults()
    graph = wandb.Graph.hook_torch(net)
    hidden = net.init_hidden()
    input_data = torch.ones((100), dtype=torch.long)
    output = net.forward(input_data, hidden)
    grads = torch.ones(2, 1000)
    graph = wandb.Graph.transform(graph)
    assert len(graph["nodes"]) == 3
    assert graph["nodes"][2]['output_shape'] == [[1,2]]

def test_resnet18():
    resnet = models.resnet18()
    graph = wandb.Graph.hook_torch(resnet)
    output = resnet.forward(torch.ones((2, 3, 224, 224), requires_grad=True))
    grads = torch.ones(2, 1000)
    output.backward(grads)
    graph = wandb.Graph.transform(graph)
    assert graph["nodes"][0]['class_name'] == "Conv2d(3, 64, kernel_size=(7, 7), stride=(2, 2), padding=(3, 3), bias=False)"