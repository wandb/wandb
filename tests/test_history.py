import pytest
import os
import json
import six
import numpy as np
from click.testing import CliRunner

from wandb.history import History
from wandb import media
import torch


@pytest.fixture
def history():
    with CliRunner().isolated_filesystem():
        yield History("wandb-history.jsonl")


def di(row):
    """Returns a dict_items object for easier comparison"""
    return six.viewitems(row)


def disk_history():
    """Reads history from disk and returns an array of dicts"""
    return History("wandb-history.jsonl").rows


def test_history_default(history):
    history.add({"loss": 0.5})
    h = disk_history()
    assert di({"loss": 0.5, "_step": 0}) <= di(h[0])
    assert "_runtime" in h[0].keys()


def test_history_multi_write(history):
    history.row.update({"epoch": 1, "val_loss": 1})
    history.add({"loss": 0.5})
    h = disk_history()
    assert di({"loss": 0.5, "val_loss": 1, "epoch": 1}) <= di(h[0])


def test_history_explicit_write(history):
    history.add({"loss": 0.5})
    history.add({"loss": 0.6})
    h = disk_history()
    assert h[0]["loss"] == 0.5
    assert h[-1]["loss"] == 0.6


def test_step_context(history):
    with history.step() as h:
        h.add({"loss": 0.2})
        h.row["epoch"] = 1
    h = disk_history()
    assert di({"loss": 0.2, "epoch": 1}) <= di(h[0])


def test_step_context_no_compute(history):
    with history.step(compute=False) as h:
        h.add({"loss": 0.2})
        h.row["epoch"] = 1
        if h.compute:
            raise ValueError()
    h = disk_history()
    assert len(h) == 0


def test_step_context_global(history):
    with history.step():
        history.add({"foo": "bar"})
    h = disk_history()
    assert di({"foo": "bar"}) <= di(h[0])


def test_stream_step(history):
    with history.stream("batch").step() as h:
        h.add({"foo": "bar"})
    h = disk_history()
    assert di({"_stream": "batch", "foo": "bar"}) <= di(h[0])


def test_list_of_images(history):
    image = np.random.randint(255, size=(28, 28))
    history.add({"images": [media.Image(image)]})
    h = disk_history()
    assert h[0]["images"] == {'_type': 'images',
                              'count': 1, 'height': 28, 'width': 28}


def test_stream(history):
    history.stream("foo").add({"acc": 1})
    h = disk_history()
    assert di({"_stream": "foo", "acc": 1}) <= di(h[0])


def test_torch(history):
    with history.step():
        history.torch.log_stats(
            torch.autograd.Variable(torch.randn(
                2, 2).type(torch.FloatTensor), requires_grad=True), "layer1")
    h = disk_history()
    assert "_layer1-0.50" in h[0].keys()


def test_torch_no_compute(history):
    with history.step(False):
        history.torch.log_stats(
            torch.autograd.Variable(torch.randn(
                2, 2).type(torch.FloatTensor), requires_grad=True), "layer1")
    h = disk_history()
    assert len(h) == 0
