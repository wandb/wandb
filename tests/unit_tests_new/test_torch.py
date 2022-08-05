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
