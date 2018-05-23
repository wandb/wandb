import pytest
from wandb.summary import Summary
from click.testing import CliRunner
from wandb import Histogram
import json


@pytest.fixture
def summary():
    with CliRunner().isolated_filesystem():
        s = Summary()
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
