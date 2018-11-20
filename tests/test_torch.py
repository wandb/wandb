import torch
import torch.nn as nn
import torch.nn.functional as F
import wandb
from pprint import pprint
from torchvision import models
from torch.autograd import Variable
from pkg_resources import parse_version

def dummy_torch_tensor(size, requires_grad=True):
    if parse_version(torch.__version__) >= parse_version('0.4'):
        return torch.ones(size, requires_grad=requires_grad)
    else:
        return torch.autograd.Variable(torch.ones(size), requires_grad=requires_grad)

class DynamicModule(nn.Module):
    def __init__(self):
        super(MyModule, self).__init__()
        self.choices = nn.ModuleDict({
                'conv': nn.Conv2d(10, 10, 3),
                'pool': nn.MaxPool2d(3)
        })
        self.activations = nn.ModuleDict([
                ['lrelu', nn.LeakyReLU()],
                ['prelu', nn.PReLU()]
        ])

    def forward(self, x, choice, act):
        x = self.choices[choice](x)
        x = self.activations[act](x)
        return x

class ParameterModule(nn.Module):
    def __init__(self):
        super(ParameterModule, self).__init__()
        self.params = nn.ParameterList([nn.Parameter(torch.ones(10, 10)) for i in range(10)])
        self.otherparam = nn.Parameter(torch.Tensor(5))

    def forward(self, x):
        # ParameterList can act as an iterable, or be indexed using ints
        for i, p in enumerate(self.params):
            x = self.params[i // 2].mm(x) + p.mm(x)
        return x

def init_conv_weights(layer, weights_std=0.01,  bias=0):
    '''Initialize weights for subnet convolution'''

    if parse_version(torch.__version__) >= parse_version('0.4'):
        nn.init.normal_(layer.weight.data, std=weights_std)
        nn.init.constant_(layer.bias.data, val=bias)
    else:
        nn.init.normal(layer.weight.data, std=weights_std)
        nn.init.constant(layer.bias.data, val=bias)
    return layer

def conv3x3(in_channels, out_channels, **kwargs):
    '''Return a 3x3 convolutional layer for SubNet'''
    layer = nn.Conv2d(in_channels, out_channels, kernel_size=3, **kwargs)
    layer = init_conv_weights(layer)

    return layer

class SubNet(nn.Module):
    def __init__(self, mode, anchors=9, classes=80, depth=4,
                 base_activation=F.relu,
                 output_activation=F.sigmoid):
        super(SubNet, self).__init__()
        self.anchors = anchors
        self.classes = classes
        self.depth = depth
        self.base_activation = base_activation
        self.output_activation = output_activation

        self.subnet_base = nn.ModuleList([conv3x3(256, 256, padding=1)
                                          for _ in range(depth)])

        if mode == 'boxes':
            self.subnet_output = conv3x3(256, 4 * self.anchors, padding=1)
        elif mode == 'classes':
            # add an extra dim for confidence
            self.subnet_output = conv3x3(256, (1 + self.classes) * self.anchors, padding=1)

        self._output_layer_init(self.subnet_output.bias.data)

    def _output_layer_init(self, tensor, pi=0.01):
        fill_constant = 4.59#- np.log((1 - pi) / pi)

        return tensor.fill_(fill_constant)

    def forward(self, x):
        for layer in self.subnet_base:
            x = self.base_activation(layer(x))

        x = self.subnet_output(x)
        x = x.permute(0, 2, 3, 1).contiguous().view(x.size(0),
                                                    x.size(2) * x.size(3) * self.anchors, -1)

        return x

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
        h_t = dummy_torch_tensor((input.size(0), 51))
        c_t = dummy_torch_tensor((input.size(0), 51))
        h_t2 = dummy_torch_tensor((input.size(0), 51))
        c_t2 = dummy_torch_tensor((input.size(0), 51))

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

def test_gradient_logging(wandb_init_run):
    net = ConvNet()
    wandb.hook_torch(net)
    for i in range(3):
        output = net(dummy_torch_tensor((64, 1, 28, 28)))
        grads = torch.ones(64, 10)
        output.backward(grads)
        assert(len(wandb_init_run.history.row) == 8)
        assert(wandb_init_run.history.row['gradients/fc2.bias'].histogram[0] > 0)
        wandb.log({"a": 2})
    assert(len(wandb_init_run.history.rows) == 3)

def test_all_logging(wandb_init_run):
    net = ConvNet()
    wandb.hook_torch(net, log="all")
    for i in range(3):
        output = net(dummy_torch_tensor((64, 1, 28, 28)))
        grads = torch.ones(64, 10)
        output.backward(grads)
        assert(len(wandb_init_run.history.row) == 16)
        assert(wandb_init_run.history.row['parameters/fc2.bias'].histogram[0] > 0)
        assert(wandb_init_run.history.row['gradients/fc2.bias'].histogram[0] > 0)
        wandb.log({"a": 2})
    assert(len(wandb_init_run.history.rows) == 3)

def test_parameter_logging(wandb_init_run):
    net = ConvNet()
    wandb.hook_torch(net, log="parameters")
    for i in range(3):
        output = net(dummy_torch_tensor((64, 1, 28, 28)))
        grads = torch.ones(64, 10)
        output.backward(grads)
        assert(len(wandb_init_run.history.row) == 8)
        assert(wandb_init_run.history.row['parameters/fc2.bias'].histogram[0] > 0)
        wandb.log({"a": 2})
    assert(len(wandb_init_run.history.rows) == 3)

def test_simple_net():
    net = ConvNet()
    graph = wandb.wandb_torch.TorchGraph.hook_torch(net)
    output = net.forward(dummy_torch_tensor((64, 1, 28, 28)))
    grads = torch.ones(64, 10)
    output.backward(grads)
    graph = wandb.Graph.transform(graph)
    assert len(graph["nodes"]) == 5
    assert graph["nodes"][0]['class_name'] == "Conv2d(1, 10, kernel_size=(5, 5), stride=(1, 1))"
    assert graph["nodes"][0]['name'] == "conv1"

def test_sequence_net():
    net = Sequence()
    graph = wandb.wandb_torch.TorchGraph.hook_torch(net)
    output = net.forward(dummy_torch_tensor(
        (97, 999)))
    output.backward(torch.zeros((97, 999)))
    graph = wandb.Graph.transform(graph)
    assert len(graph["nodes"]) == 3
    assert len(graph["nodes"][0]['parameters']) == 4
    assert graph["nodes"][0]['class_name'] == "LSTMCell(1, 51)"
    assert graph["nodes"][0]['name'] == "lstm1"

def test_multi_net(wandb_init_run):
    net = ConvNet()
    graphs = wandb.hook_torch((net, net))
    output = net.forward(dummy_torch_tensor((64, 1, 28, 28)))
    grads = torch.ones(64, 10)
    output.backward(grads)
    graph1 = wandb.Graph.transform(graphs[0])
    graph2 = wandb.Graph.transform(graphs[1])
    assert len(graph1["nodes"]) == 5
    assert len(graph2["nodes"]) == 5

def test_alex_net():
    alex = models.AlexNet()
    graph = wandb.wandb_torch.TorchGraph.hook_torch(alex)
    output = alex.forward(dummy_torch_tensor((2, 3, 224, 224)))
    grads = torch.ones(2, 1000)
    output.backward(grads)
    graph = wandb.Graph.transform(graph)
    assert len(graph["nodes"]) == 20
    assert graph["nodes"][0]['class_name'] == "Conv2d(3, 64, kernel_size=(11, 11), stride=(4, 4), padding=(2, 2))"
    assert graph["nodes"][0]['name'] == "features.0"

def test_lstm(wandb_init_run):
    if parse_version(torch.__version__) < parse_version('0.4'):
        return

    net = LSTMModel(2,2)
    graph = wandb.wandb_torch.TorchGraph.hook_torch(net)

    hidden = net.init_hidden()
    input_data = torch.ones((100)).type(torch.LongTensor)
    output = net.forward(input_data, hidden)
    grads = torch.ones(2, 1000)
    graph = wandb.Graph.transform(graph)
    
    assert len(graph["nodes"]) == 3
    assert graph["nodes"][2]['output_shape'] == [[1,2]]
    
def test_resnet18():
    resnet = models.resnet18()
    graph = wandb.wandb_torch.TorchGraph.hook_torch(resnet)
    output = resnet.forward(dummy_torch_tensor((2, 3, 224, 224)))

    grads = torch.ones(2, 1000)
    output.backward(grads)
    graph = wandb.Graph.transform(graph)
    assert graph["nodes"][0]['class_name'] == "Conv2d(3, 64, kernel_size=(7, 7), stride=(2, 2), padding=(3, 3), bias=False)"

def test_subnet():
    subnet = SubNet("boxes")
    graph = wandb.wandb_torch.TorchGraph.hook_torch(subnet)
    output = subnet.forward(dummy_torch_tensor((256, 256, 3, 3)))

    grads = torch.ones(256, 81, 4)
    output.backward(grads)
    graph = wandb.Graph.transform(graph)
    assert graph["nodes"][0]['class_name'] == "Conv2d(256, 256, kernel_size=(3, 3), stride=(1, 1), padding=(1, 1))"

def test_false_requires_grad(wandb_init_run):
    """When we set requires_grad to False, wandb must not
    add a hook to the variable"""

    net = ConvNet()
    net.fc1.weight.requires_grad = False
    wandb.watch(net)
    output = net(dummy_torch_tensor((64, 1, 28, 28)))
    grads = torch.ones(64, 10)
    output.backward(grads)

    # 7 gradients are logged because fc1.weight is fixed
    assert(len(wandb_init_run.history.row) == 7)
    


