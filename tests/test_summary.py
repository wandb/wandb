import pytest
from wandb.summary import FileSummary
from click.testing import CliRunner
from wandb import Histogram
import numpy as np
import os
import json
import torch
import tensorflow as tf
import pandas as pd


@pytest.fixture
def summary():
    with CliRunner().isolated_filesystem():
        s = FileSummary()
        s.update({"foo": "init"})
        yield s


def test_set_attrs(summary):
    summary.foo = "bar"
    assert json.load(open("wandb-summary.json")) == {"foo": "bar"}


def test_get_attr(summary):
    assert summary.foo == "init"


def test_update(summary):
    summary.update({"foo": "bar"})
    assert json.load(open("wandb-summary.json")) == {"foo": "bar"}


def test_update_histogram(summary):
    summary.update({"hist": Histogram(np_histogram=([1, 2, 3], [1, 2, 3, 4]))})
    assert json.load(open("wandb-summary.json")) == {
        'foo': 'init',
        "hist": {"_type": "histogram", "values": [1, 2, 3], "bins": [1, 2, 3, 4]}}


def test_set_histogram(summary):
    summary["hist"] = Histogram(np_histogram=([1, 2, 3], [1, 2, 3, 4]))
    assert json.load(open("wandb-summary.json")) == {
        'foo': 'init',
        "hist": {"_type": "histogram", "values": [1, 2, 3], "bins": [1, 2, 3, 4]}}


def test_set_item(summary):
    summary["foo"] = "bar"
    assert json.load(open("wandb-summary.json")) == {"foo": "bar"}


def test_get_item(summary):
    assert summary["foo"] == "init"


def test_delete(summary):
    summary.update({"foo": "bar", "bad": True})
    del summary["bad"]
    assert json.load(open("wandb-summary.json")) == {"foo": "bar"}


def test_big_numpy(summary):
    summary.update({"rad": np.random.rand(1000)})
    assert json.load(open("wandb-summary.json"))["rad"]["max"] > 0
    assert os.path.exists("wandb.h5")


def test_big_nested_numpy(summary):
    summary.update({"rad": {"deep": np.random.rand(1000)}})
    assert json.load(open("wandb-summary.json"))["rad"]["deep"]["max"] > 0
    assert os.path.exists("wandb.h5")


def test_torch_tensor(summary):
    summary.update({"pytorch": torch.rand(1000, 1000)})
    assert os.path.exists("wandb.h5")
    assert json.load(open("wandb-summary.json")
                     )["pytorch"]["_type"] == "torch.Tensor"


def test_tensorflow_tensor(summary):
    with tf.Session().as_default():
        summary.update({"tensorflow": tf.random_normal([1000])})
    assert os.path.exists("wandb.h5")
    assert json.load(open("wandb-summary.json")
                     )["tensorflow"]["_type"] == "tensorflow.Tensor"


def test_pandas(summary):
    summary.update({"pandas": pd.DataFrame(data=np.random.rand(1000))})
    assert os.path.exists("wandb.h5")
    parsed = json.load(open("wandb-summary.json"))
    print(parsed)
    assert parsed["pandas"]["_type"] == "pandas.DataFrame"


def test_read_numpy(summary):
    summary.update({"rad": np.random.rand(1000)})
    s = FileSummary()
    assert len(s["rad"]) == 1000


def test_read_nested_numpy(summary):
    summary.update({"rad": {"deep": np.random.rand(1000)}})
    s = FileSummary()
    assert len(s["rad"]["deep"]) == 1000
