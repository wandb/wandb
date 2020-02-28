import torch
import torch.nn as nn
import torch.nn.functional as F
import wandb
import pytest
import json
import os
import sys
import time
from pprint import pprint
from torchvision import models
from torch.autograd import Variable
from pkg_resources import parse_version

# Tests which rely on row history in memory should set `History.keep_rows = True`
from wandb.history import History
History.keep_rows = True

# TODO: FLAKY SPECS sometimes these specs are timing out

def dummy_torch_tensor(size, requires_grad=True):
    if parse_version(torch.__version__) >= parse_version('0.4'):
        return torch.ones(size, requires_grad=requires_grad)
    else:
        return torch.autograd.Variable(torch.ones(size), requires_grad=requires_grad)


class DynamicModule(nn.Module):
    def __init__(self):
        super(DynamicModule, self).__init__()
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

class Discrete(nn.Module):
    def __init__(self):
        super(Discrete, self).__init__()

    def forward(self, x):
        return nn.functional.softmax(x, dim=0)

class DiscreteModel(nn.Module):
    def __init__(self, num_outputs=2):
        super(DiscreteModel, self).__init__()
        self.linear1 = nn.Linear(1, 10)
        self.linear2 = nn.Linear(10, num_outputs)
        self.dist = Discrete()

    def forward(self, x):
        x = self.linear1(x)
        x = self.linear2(x)
        return self.dist(x)

class ParameterModule(nn.Module):
    def __init__(self):
        super(ParameterModule, self).__init__()
        self.params = nn.ParameterList(
            [nn.Parameter(torch.ones(10, 10)) for i in range(10)])
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
            self.subnet_output = conv3x3(
                256, (1 + self.classes) * self.anchors, padding=1)

        self._output_layer_init(self.subnet_output.bias.data)

    def _output_layer_init(self, tensor, pi=0.01):
        fill_constant = 4.59  # - np.log((1 - pi) / pi)

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


class FCLayer(nn.Module):
    """FC Layer + Activation"""

    def __init__(self, dims, batchnorm_dim=0, act='ReLU', dropout=0):
        super(FCLayer, self).__init__()
        layers = []
        for i in range(len(dims) - 2):
            in_dim = dims[i]  # input
            out_dim = dims[i + 1]  # output

            if 0 < dropout:
                layers.append(nn.Dropout(dropout))
            print("BOOM", in_dim, out_dim)
            layers.append(nn.Linear(in_dim, out_dim))

            if '' != act:
                layers.append(getattr(nn, act)())
            if batchnorm_dim > 0:
                layers.append(nn.BatchNorm1d(batchnorm_dim))

        if 0 < dropout:
            layers.append(nn.Dropout(dropout))
        layers.append(nn.Linear(dims[-2], dims[-1]))

        if '' != act:
            layers.append(getattr(nn, act)())

        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


class VGGConcator(nn.Module):
    """
    Extracts feature of each four panels, concatenates 4 vgg features panel-wise.
    """

    def __init__(self):
        super(VGGConcator, self).__init__()
        self.vgg = models.vgg16(pretrained=False)
        self.vgg.classifier = nn.Sequential(
            *list(self.vgg.classifier.children())[:-1])

    def forward(self, panels, num=1):
        if num == 1:
            features = self.vgg(panels)
        else:
            img0 = panels[:, 0, :, :, :]
            img1 = panels[:, 1, :, :, :]
            img2 = panels[:, 2, :, :, :]
            img3 = panels[:, 3, :, :, :]

            feature0 = self.vgg(img0)
            feature1 = self.vgg(img1)
            feature2 = self.vgg(img2)
            feature3 = self.vgg(img3)

            features = torch.cat((feature0[:, None, :], feature1[:, None, :],
                                  feature2[:, None, :], feature3[:, None, :]), dim=1)

        return features


class Embedding(nn.Module):
    def __init__(self, d_embedding, d_word, d_hidden, word_dim, dropout, sparse=False):
        super(Embedding, self).__init__()

        glove = torch.ones((10, 300))
        self.vgg = VGGConcator()
        # self.fine_tuning()
        self.word_dim = word_dim
        glove = glove[:self.word_dim]

        self.d_word = d_word
        self.emb = nn.Embedding(word_dim, 300, padding_idx=0, sparse=sparse)
        self.emb.weight.data = glove

        # consts
        self.d_img = 4096
        self.num_panels = 4
        self.num_max_sentences = 3
        self.num_max_words = 20

        self.img_fc0 = FCLayer([self.d_img, d_hidden], dropout=dropout)

        self.box_lstm = nn.LSTM(
            300, d_word, 1, batch_first=True, bidirectional=False)
        self.fc0 = FCLayer([d_word + d_hidden, d_embedding])

    def forward(self, images, words):
        words = words.long()
        batch_size = words.size(0)
        box_hidden = self.init_hidden(batch_size, self.d_word, 1, 4)

        words = words.view(-1, words.size(-1))
        emb_word = self.emb(words)
        print("Shapes: ", emb_word.shape, words.shape)
        emb_word = emb_word.view(-1, self.num_panels,
                                 self.num_max_sentences, self.num_max_words, self.d_word)
        emb_sentence = torch.sum(emb_word, dim=3)
        emb_sentence = emb_sentence.view(-1,
                                         self.num_max_sentences, self.d_word)
        lstmed_sentence, _ = self.box_lstm(emb_sentence, box_hidden)
        emb_panel_sentence = lstmed_sentence[:, -1, :]

        emb_panel_sentence = emb_panel_sentence.view(
            -1, self.num_panels, self.d_word)

        img_feature = self.vgg(images, num=4)
        img_feature = self.img_fc0(img_feature)

        fusion = torch.cat((img_feature, emb_panel_sentence), dim=-1)
        fusion = self.fc0(fusion)
        return fusion

    def init_hidden(self, batch, out, direction=1, n=1):
        dims = (direction, batch * n, out)
        hiddens = (Variable(torch.zeros(*dims)),
                   Variable(torch.zeros(*dims)))
        return hiddens

@pytest.mark.skipif(sys.version_info < (3, 6), reason="Timeouts in older python versions")
def test_embedding(wandb_init_run):
    net = Embedding(d_embedding=300, d_word=300,
                    d_hidden=300, word_dim=100, dropout=0)
    wandb.watch(net, log="all", log_freq=1)
    for i in range(2):
        output = net(torch.ones((1, 4, 3, 224, 224)),
                     torch.ones((1, 4, 3, 20)))
        output.backward(torch.ones(1, 4, 300))
        wandb.log({"loss": 1})
    assert len(wandb_init_run.history.rows[0]) == 82


@pytest.mark.skipif(sys.version_info < (3, 6), reason="Timeouts in older python versions")
def test_sparse_embedding(wandb_init_run):
    net = Embedding(d_embedding=300, d_word=300,
                    d_hidden=300, word_dim=100, dropout=0, sparse=True)
    wandb.watch(net, log="all", log_freq=1)
    for i in range(2):
        output = net(torch.ones((1, 4, 3, 224, 224)),
                     torch.ones((1, 4, 3, 20)))
        output.backward(torch.ones(1, 4, 300))
        wandb.log({"loss": 1})
    assert len(wandb_init_run.history.rows[0]) == 82

def test_categorical(wandb_init_run):
    net = DiscreteModel(num_outputs=2)
    wandb.watch(net, log="all", log_freq=1)
    for i in range(2):
        output = net(torch.ones((1)))
        samp = output.backward(torch.ones((2)))
        wandb.log({"loss": samp})
    assert wandb_init_run.summary["graph_0"]._to_graph_json()
    assert len(wandb_init_run.history.rows[0]) == 12

def test_double_log(wandb_init_run):
    net = ConvNet()
    wandb.watch(net)
    with pytest.raises(ValueError):
        wandb.watch(net)


def test_gradient_logging(wandb_init_run):
    net = ConvNet()
    wandb.watch(net, log_freq=1)
    for i in range(3):
        output = net(dummy_torch_tensor((64, 1, 28, 28)))
        grads = torch.ones(64, 10)
        output.backward(grads)
        assert(len(wandb_init_run.history.row) == 8)
        assert(
            wandb_init_run.history.row['gradients/fc2.bias'].histogram[0] > 0)
        wandb.log({"a": 2})
    assert(len(wandb_init_run.history.rows) == 3)

def test_unwatch(wandb_init_run):
    net = ConvNet()
    wandb.watch(net, log_freq=1, log="all")
    wandb.unwatch()
    for i in range(3):
        output = net(dummy_torch_tensor((64, 1, 28, 28)))
        grads = torch.ones(64, 10)
        output.backward(grads)
        assert(len(wandb_init_run.history.row) == 0)
        assert(
            wandb_init_run.history.row.get('gradients/fc2.bias') is None)
        wandb.log({"a": 2})
    assert(len(wandb_init_run.history.rows) == 3)

def test_unwatch_multi(wandb_init_run):
    net1 = ConvNet()
    net2 = ConvNet()
    wandb.watch(net1, log_freq=1, log="all")
    wandb.watch(net2, log_freq=1, log="all")
    wandb.unwatch(net1)
    for i in range(3):
        output1 = net1(dummy_torch_tensor((64, 1, 28, 28)))
        output2 = net2(dummy_torch_tensor((64, 1, 28, 28)))
        grads = torch.ones(64, 10)
        output1.backward(grads)
        output2.backward(grads)
        assert(len(wandb_init_run.history.row) == 16)
        print(wandb_init_run.history.row)
        assert wandb_init_run.history.row.get('gradients/graph_1conv1.bias')
        assert wandb_init_run.history.row.get('gradients/conv1.bias') is None
        wandb.log({"a": 2})
    assert(len(wandb_init_run.history.rows) == 3)

@pytest.mark.skipif(sys.version_info < (3, 6), reason="Timeouts in older python versions")
def test_gradient_logging_freq(wandb_init_run):
    net = ConvNet()
    log_freq = 50
    wandb.watch(net, log_freq=log_freq)
    for i in range(110):
        output = net(dummy_torch_tensor((64, 1, 28, 28)))
        grads = torch.ones(64, 10)
        output.backward(grads)
        if (i + 1) % log_freq == 0:
            assert(len(wandb_init_run.history.row) == 8)
            assert(
                wandb_init_run.history.row['gradients/fc2.bias'].histogram[0] > 0)
        else:
            assert(len(wandb_init_run.history.row) == 0)
        wandb.log({"a": 2})
    assert(len(wandb_init_run.history.rows) == 110)


def test_all_logging(wandb_init_run):
    net = ConvNet()
    wandb.watch(net, log="all", log_freq=1)
    for i in range(3):
        output = net(dummy_torch_tensor((64, 1, 28, 28)))
        grads = torch.ones(64, 10)
        output.backward(grads)
        assert(len(wandb_init_run.history.row) == 16)
        assert(
            wandb_init_run.history.row['parameters/fc2.bias'].histogram[0] > 0)
        assert(
            wandb_init_run.history.row['gradients/fc2.bias'].histogram[0] > 0)
        wandb.log({"a": 2})
    assert(len(wandb_init_run.history.rows) == 3)

@pytest.mark.skipif(sys.version_info < (3, 6), reason="Timeouts in older python versions")
def test_all_logging_freq(wandb_init_run):
    net = ConvNet()
    log_freq = 50
    wandb.watch(net, log="all", log_freq=log_freq)
    for i in range(110):
        output = net(dummy_torch_tensor((64, 1, 28, 28)))
        grads = torch.ones(64, 10)
        output.backward(grads)
        if (i + 1) % log_freq == 0:
            assert(len(wandb_init_run.history.row) == 16)
            assert(
                wandb_init_run.history.row['parameters/fc2.bias'].histogram[0] > 0)
            assert(
                wandb_init_run.history.row['gradients/fc2.bias'].histogram[0] > 0)
        else:
            assert(len(wandb_init_run.history.row) == 0)
        wandb.log({"a": 2})
    assert(len(wandb_init_run.history.rows) == 110)

# These were timing out in old python
@pytest.mark.skipif(sys.version_info < (3, 6), reason="Timeouts in older python versions")
def test_parameter_logging(wandb_init_run):
    net = ConvNet()
    wandb.watch(net, log="parameters", log_freq=1)
    for i in range(3):
        output = net(dummy_torch_tensor((64, 1, 28, 28)))
        grads = torch.ones(64, 10)
        output.backward(grads)
        assert(len(wandb_init_run.history.row) == 8)
        assert(
            wandb_init_run.history.row['parameters/fc2.bias'].histogram[0] > 0)
        wandb.log({"a": 2})
    assert wandb_init_run.summary["graph_0"]
    file_summary = json.loads(
        open(os.path.join(wandb_init_run.dir, "wandb-summary.json")).read())
    assert file_summary["graph_0"]
    assert(len(wandb_init_run.history.rows) == 3)

@pytest.mark.skipif(sys.version_info < (3, 6), reason="Timeouts in older python versions")
def test_parameter_logging_freq(wandb_init_run):
    net = ConvNet()
    log_freq = 20
    wandb.hook_torch(net, log="parameters", log_freq=log_freq)
    for i in range(50):
        #TO debug timeouts
        print("i: %i, time: %s" % (i, time.time()))
        output = net(dummy_torch_tensor((64, 1, 28, 28)))
        grads = torch.ones(64, 10)
        output.backward(grads)
        if (i + 1) % log_freq == 0:
            assert(len(wandb_init_run.history.row) == 8)
            assert(
                wandb_init_run.history.row['parameters/fc2.bias'].histogram[0] > 0)
        else:
            assert(len(wandb_init_run.history.row) == 0)
        wandb.log({"a": 2})
    assert(len(wandb_init_run.history.rows) == 50)

@pytest.mark.skipif(sys.version_info == (3, 6), reason="Timeouts in 3.6 for some reason...")
def test_simple_net():
    net = ConvNet()
    graph = wandb.wandb_torch.TorchGraph.hook_torch(net)
    output = net.forward(dummy_torch_tensor((64, 1, 28, 28)))
    grads = torch.ones(64, 10)
    output.backward(grads)
    graph = graph._to_graph_json()
    assert len(graph["nodes"]) == 5
    assert graph["nodes"][0]['class_name'] == "Conv2d(1, 10, kernel_size=(5, 5), stride=(1, 1))"
    assert graph["nodes"][0]['name'] == "conv1"


def test_sequence_net():
    net = Sequence()
    graph = wandb.wandb_torch.TorchGraph.hook_torch(net)
    output = net.forward(dummy_torch_tensor(
        (97, 100)))
    output.backward(torch.zeros((97, 100)))
    graph = graph._to_graph_json()
    assert len(graph["nodes"]) == 3
    assert len(graph["nodes"][0]['parameters']) == 4
    assert graph["nodes"][0]['class_name'] == "LSTMCell(1, 51)"
    assert graph["nodes"][0]['name'] == "lstm1"


def test_multi_net(wandb_init_run):
    net1 = ConvNet()
    net2 = ConvNet()
    graphs = wandb.watch((net1, net2))
    output1 = net1.forward(dummy_torch_tensor((64, 1, 28, 28)))
    output2 = net2.forward(dummy_torch_tensor((64, 1, 28, 28)))
    grads = torch.ones(64, 10)
    output1.backward(grads)
    output2.backward(grads)
    graph1 = graphs[0]._to_graph_json()
    graph2 = graphs[1]._to_graph_json()
    assert len(graph1["nodes"]) == 5
    assert len(graph2["nodes"]) == 5

def test_multi_net_global(wandb_init_run):
    net1 = ConvNet()
    net2 = ConvNet()
    wandb.watch(net1)
    wandb.watch(net2)
    output1 = net1.forward(dummy_torch_tensor((64, 1, 28, 28)))
    output2 = net2.forward(dummy_torch_tensor((64, 1, 28, 28)))
    grads = torch.ones(64, 10)
    output1.backward(grads)
    output2.backward(grads)
    assert wandb.run.summary["graph_1"]


def test_alex_net():
    alex = models.AlexNet()
    graph = wandb.wandb_torch.TorchGraph.hook_torch(alex)
    output = alex.forward(dummy_torch_tensor((2, 3, 224, 224)))
    grads = torch.ones(2, 1000)
    output.backward(grads)
    graph = graph._to_graph_json()
    # This was failing in CI with 21 nodes?!?
    print(graph["nodes"])
    assert len(graph["nodes"]) >= 20
    assert graph["nodes"][0]['class_name'] == "Conv2d(3, 64, kernel_size=(11, 11), stride=(4, 4), padding=(2, 2))"
    assert graph["nodes"][0]['name'] == "features.0"


def test_lstm(wandb_init_run):
    if parse_version(torch.__version__) < parse_version('0.4'):
        return

    net = LSTMModel(2, 2)
    graph = wandb.wandb_torch.TorchGraph.hook_torch(net)

    hidden = net.init_hidden()
    input_data = torch.ones((100)).type(torch.LongTensor)
    output = net.forward(input_data, hidden)
    grads = torch.ones(2, 1000)
    graph = graph._to_graph_json()

    assert len(graph["nodes"]) == 3
    assert graph["nodes"][2]['output_shape'] == [[1, 2]]


def test_resnet18():
    resnet = models.resnet18()
    graph = wandb.wandb_torch.TorchGraph.hook_torch(resnet)
    output = resnet.forward(dummy_torch_tensor((2, 3, 224, 224)))

    grads = torch.ones(2, 1000)
    output.backward(grads)
    graph = graph._to_graph_json()
    assert graph["nodes"][0]['class_name'] == "Conv2d(3, 64, kernel_size=(7, 7), stride=(2, 2), padding=(3, 3), bias=False)"


def test_subnet():
    subnet = SubNet("boxes")
    graph = wandb.wandb_torch.TorchGraph.hook_torch(subnet)
    output = subnet.forward(dummy_torch_tensor((256, 256, 3, 3)))

    grads = torch.ones(256, 81, 4)
    output.backward(grads)
    graph = graph._to_graph_json()
    assert graph["nodes"][0]['class_name'] == "Conv2d(256, 256, kernel_size=(3, 3), stride=(1, 1), padding=(1, 1))"


def test_false_requires_grad(wandb_init_run):
    """When we set requires_grad to False, wandb must not
    add a hook to the variable"""

    net = ConvNet()
    net.fc1.weight.requires_grad = False
    wandb.watch(net, log_freq=1)
    output = net(dummy_torch_tensor((64, 1, 28, 28)))
    grads = torch.ones(64, 10)
    output.backward(grads)

    # 7 gradients are logged because fc1.weight is fixed
    assert(len(wandb_init_run.history.row) == 7)


def test_nested_shape():
    shape = wandb.wandb_torch.nested_shape([2,4,5])
    assert shape == [[],[],[]]
    shape = wandb.wandb_torch.nested_shape([dummy_torch_tensor((2,3)),dummy_torch_tensor((4,5))])
    assert shape == [[2,3],[4,5]]
    # create recursive lists of tensors (t3 includes itself)
    t1 = dummy_torch_tensor((2,3))
    t2 = dummy_torch_tensor((4,5))
    t3 = [t1, t2]
    t3.append(t3)
    t3.append(t2)
    shape = wandb.wandb_torch.nested_shape([t1, t2, t3])
    assert shape == [[2, 3], [4, 5], [[2, 3], [4, 5], 0, [4, 5]]]
