import pytest
import torch
import torch.nn as nn
import wandb


def test_nested_shape():
    shape = wandb.wandb_torch.nested_shape([2, 4, 5])
    assert shape == [[], [], []]

    shape = wandb.wandb_torch.nested_shape(
        [
            torch.ones((2, 3), requires_grad=True),
            torch.ones((4, 5), requires_grad=True),
        ]
    )
    assert shape == [[2, 3], [4, 5]]

    # create recursive lists of tensors (t3 includes itself)
    t1 = torch.ones((2, 3), requires_grad=True)
    t2 = torch.ones((4, 5), requires_grad=True)
    t3 = [t1, t2]
    t3.append(t3)
    t3.append(t2)
    shape = wandb.wandb_torch.nested_shape([t1, t2, t3])
    assert shape == [[2, 3], [4, 5], [[2, 3], [4, 5], 0, [4, 5]]]


@pytest.mark.parametrize(
    "test_input,expected",
    [
        (torch.Tensor([1.0, 2.0, 3.0]), False),
        (torch.Tensor([0.0, 0.0, 0.0]), False),
        (torch.Tensor([1.0]), False),
        (torch.Tensor([]), True),
        (torch.Tensor([1.0, float("nan"), float("nan")]), False),
        (torch.Tensor([1.0, float("inf"), -float("inf")]), False),
        (torch.Tensor([1.0, float("nan"), float("inf")]), False),
        (torch.Tensor([float("nan"), float("nan"), float("nan")]), True),
        (torch.Tensor([float("inf"), float("inf"), -float("inf")]), True),
        (torch.Tensor([float("nan"), float("inf"), -float("inf")]), True),
    ],
)
def test_no_finite_values(test_input, expected):
    torch_history = wandb.wandb_torch.TorchHistory()

    assert torch_history._no_finite_values(test_input) is expected


@pytest.mark.parametrize(
    "test_input,expected",
    [
        (torch.Tensor([0.0, 1.0, 2.0]), torch.Tensor([0.0, 1.0, 2.0])),
        (torch.Tensor([1.0]), torch.Tensor([1.0])),
        (torch.Tensor([0.0, float("inf"), -float("inf")]), torch.Tensor([0.0])),
        (torch.Tensor([0.0, float("nan"), float("inf")]), torch.Tensor([0.0])),
    ],
)
def test_remove_infs_nans(test_input, expected):
    torch_history = wandb.wandb_torch.TorchHistory()

    assert torch.equal(torch_history._remove_infs_nans(test_input), expected)


def test_double_log(mock_run):
    run = mock_run()
    net = nn.Linear(10, 2)
    run.watch(net, log_graph=True)
    with pytest.raises(ValueError):
        run.watch(net, log_graph=True)


@pytest.mark.parametrize("log_type", ["parameters", "all"])
def test_watch_parameters_torch_jit(mock_run, capsys, log_type):
    run = mock_run(use_magic_mock=True)
    net = torch.jit.script(nn.Linear(10, 2))
    run.watch(net, log=log_type)

    outerr = capsys.readouterr()
    assert "skipping parameter tracking" in outerr.err


def test_watch_graph_torch_jit(mock_run, capsys):
    run = mock_run(use_magic_mock=True)

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.layer_1 = nn.Linear(10, 2)

        def forward(self, x):
            return self.layer_1(x)

    net = torch.jit.script(Net())
    run.watch(net, log_graph=True)

    outerr = capsys.readouterr()
    assert "skipping graph tracking" in outerr.err


def test_watch_bad_argument(mock_run):
    run = mock_run(use_magic_mock=True)
    net = nn.Linear(10, 2)
    with pytest.raises(
        ValueError, match="log must be one of 'gradients', 'parameters', 'all', or None"
    ):
        run.watch(net, log="bad_argument")
