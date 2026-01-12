from __future__ import annotations

import pytest
import wandb
import wandb.sdk

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F  # noqa: N812
except ImportError:

    class nn:  # noqa: N801
        Module = object


def dummy_torch_tensor(size, requires_grad=True):
    return torch.ones(size, requires_grad=requires_grad)


class DynamicModule(nn.Module):
    def __init__(self):
        super().__init__()
        self.choices = nn.ModuleDict(
            {"conv": nn.Conv2d(10, 10, 3), "pool": nn.MaxPool2d(3)}
        )
        self.activations = nn.ModuleDict(
            [["lrelu", nn.LeakyReLU()], ["prelu", nn.PReLU()]]
        )

    def forward(self, x, choice, act):
        x = self.choices[choice](x)
        x = self.activations[act](x)
        return x


class EmbModel(nn.Module):
    def __init__(self, x=16, y=32):
        super().__init__()
        self.emb1 = nn.Embedding(x, y)
        self.emb2 = nn.Embedding(x, y)

    def forward(self, x):
        return {
            "key": {
                "emb1": self.emb1(x),
                "emb2": self.emb2(x),
            }
        }


class EmbModelWrapper(nn.Module):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.emb = EmbModel(*args, **kwargs)

    def forward(self, *args, **kwargs):
        return self.emb(*args, **kwargs)


class Discrete(nn.Module):
    def __init__(self):
        super().__init__()

    def forward(self, x):
        return nn.functional.softmax(x, dim=0)


class DiscreteModel(nn.Module):
    def __init__(self, num_outputs=2):
        super().__init__()
        self.linear1 = nn.Linear(1, 10)
        self.linear2 = nn.Linear(10, num_outputs)
        self.dist = Discrete()

    def forward(self, x):
        x = self.linear1(x)
        x = self.linear2(x)
        return self.dist(x)


class ParameterModule(nn.Module):
    def __init__(self):
        super().__init__()
        self.params = nn.ParameterList(
            [nn.Parameter(torch.ones(10, 10)) for i in range(10)]
        )
        self.otherparam = nn.Parameter(torch.Tensor(5))

    def forward(self, x):
        # ParameterList can act as an iterable, or be indexed using ints
        for i, p in enumerate(self.params):
            x = self.params[i // 2].mm(x) + p.mm(x)
        return x


class Sequence(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm1 = nn.LSTMCell(1, 51)
        self.lstm2 = nn.LSTMCell(51, 51)
        self.linear = nn.Linear(51, 1)

    def forward(self, input, future=0):
        outputs = []
        h_t = dummy_torch_tensor((input.size(0), 51))
        c_t = dummy_torch_tensor((input.size(0), 51))
        h_t2 = dummy_torch_tensor((input.size(0), 51))
        c_t2 = dummy_torch_tensor((input.size(0), 51))

        for _, input_t in enumerate(input.chunk(input.size(1), dim=1)):
            h_t, c_t = self.lstm1(input_t, (h_t, c_t))
            h_t2, c_t2 = self.lstm2(h_t, (h_t2, c_t2))
            output = self.linear(h_t2)
            outputs += [output]
        for _ in range(future):  # if we should predict the future
            h_t, c_t = self.lstm1(output, (h_t, c_t))
            h_t2, c_t2 = self.lstm2(h_t, (h_t2, c_t2))
            output = self.linear(h_t2)
            outputs += [output]
        outputs = torch.stack(outputs, 1).squeeze(2)
        return outputs


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


def init_conv_weights(layer, weights_std=0.01, bias=0):
    """Initialize weights for subnet convolution."""
    nn.init.normal_(layer.weight.data, std=weights_std)
    nn.init.constant_(layer.bias.data, val=bias)
    return layer


def conv3x3(in_channels, out_channels, **kwargs):
    """Return a 3x3 convolutional layer for SubNet."""
    layer = nn.Conv2d(in_channels, out_channels, kernel_size=3, **kwargs)
    layer = init_conv_weights(layer)

    return layer


# TODO(jhr): does not work with --flake-finder
@pytest.mark.xfail(reason="TODO: fix this test")
def test_all_logging(wandb_backend_spy):
    pytest.importorskip("torch")
    n = 3
    run = wandb.init()
    net = ConvNet()
    run.watch(
        net,
        log="all",
        log_freq=1,
    )
    for _ in range(n):
        output = net(
            dummy_torch_tensor(
                (32, 1, 28, 28),
            )
        )
        grads = torch.ones(32, 10)
        output.backward(grads)
        run.log({"a": 2})
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        for keys, item in history.items():
            assert len(item) == 20
            assert keys in (0, 1, 2)
            assert len(item["parameters/fc2.bias"]["bins"]) == 65
            assert len(item["gradients/fc2.bias"]["bins"]) == 65


def test_embedding_dict_watch(wandb_backend_spy):
    pytest.importorskip("torch")
    run = wandb.init()
    model = EmbModelWrapper()
    run.watch(model, log_freq=1, idx=0)
    opt = torch.optim.Adam(params=model.parameters())
    inp = torch.randint(16, [8, 5])
    out = model(inp)
    out = (out["key"]["emb1"]).sum(-1)
    loss = F.mse_loss(out, inp.float())
    loss.backward()
    opt.step()
    run.log({"loss": loss})
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert len(history[0]["gradients/emb.emb1.weight"]["bins"]) == 65
        assert history[0]["gradients/emb.emb1.weight"]["_type"] == "histogram"


@pytest.mark.timeout(120)
def test_sequence_net(user):
    """Test logging a sequence model.

    Use intrenal function wandb.sdk._watch to query the graph object.
    """
    pytest.importorskip("torch")
    with wandb.init() as run:
        net = Sequence()
        graph = wandb.sdk._watch(run, net, log_graph=True)[0]
        output = net.forward(dummy_torch_tensor((97, 100)))
        output.backward(torch.zeros((97, 100)))
        graph = graph._to_graph_json()

        assert len(graph["nodes"]) == 3
        assert len(graph["nodes"][0]["parameters"]) == 4
        assert graph["nodes"][0]["class_name"] == "LSTMCell(1, 51)"
        assert graph["nodes"][0]["name"] == "lstm1"


def test_multi_net(user):
    pytest.importorskip("torch")
    with wandb.init() as run:
        net1 = ConvNet()
        net2 = ConvNet()
        graphs = wandb.sdk._watch(run, (net1, net2), log_graph=True)
        output1 = net1.forward(dummy_torch_tensor((64, 1, 28, 28)))
        output2 = net2.forward(dummy_torch_tensor((64, 1, 28, 28)))
        grads = torch.ones(64, 10)
        output1.backward(grads)
        output2.backward(grads)
        graph1 = graphs[0]._to_graph_json()
        graph2 = graphs[1]._to_graph_json()
        assert len(graph1["nodes"]) == 5
        assert len(graph2["nodes"]) == 5
