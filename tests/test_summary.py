import matplotlib
# this needs to be called before importing wandb Graph
matplotlib.use("Agg")


from wandb import wandb_run
from wandb.summary import FileSummary
import pandas
import tensorflow as tf
import torch
import json
import glob
import os
import numpy as np
import tempfile
import plotly.graph_objs as go
import matplotlib.pyplot as plt
from wandb import Histogram, Image, Graph, Table
from wandb.data_types import Node
from click.testing import CliRunner
import pytest


@pytest.fixture
def summary():
    with CliRunner().isolated_filesystem():
        run = wandb_run.Run()
        run.summary.update({"foo": "init"})
        yield run.summary


def disk_summary(summary):
    return json.load(open(summary._fname))


def test_set_attrs(summary):
    summary.foo = "bar"
    assert disk_summary(summary) == {"foo": "bar"}


def test_get_attr(summary):
    assert summary.foo == "init"


def test_update(summary):
    summary.update({"foo": "bar"})
    assert disk_summary(summary) == {"foo": "bar"}


def test_update_histogram(summary):
    summary.update({"hist": Histogram(np_histogram=([1, 2, 3], [1, 2, 3, 4]))})
    assert disk_summary(summary) == {
        'foo': 'init',
        "hist": {"_type": "histogram", "values": [1, 2, 3], "bins": [1, 2, 3, 4]}}


def test_set_histogram(summary):
    summary["hist"] = Histogram(np_histogram=([1, 2, 3], [1, 2, 3, 4]))
    assert disk_summary(summary) == {
        'foo': 'init',
        "hist": {"_type": "histogram", "values": [1, 2, 3], "bins": [1, 2, 3, 4]}}


def test_set_item(summary):
    summary["foo"] = "bar"
    assert disk_summary(summary) == {"foo": "bar"}


def test_get_item(summary):
    assert summary["foo"] == "init"


def test_delete(summary):
    summary.update({"foo": "bar", "bad": True})
    assert summary['foo'] == 'bar'
    assert summary['bad'] is True
    del summary["bad"]
    assert disk_summary(summary) == {"foo": "bar"}


def test_image(summary):
    summary["image"] = Image(np.zeros((28, 28)))
    ds = disk_summary(summary)
    assert os.path.exists(os.path.join(summary._run.dir, ds['image']['path']))

    expected = {
        '_type': 'image-file',
        'height': 28,
        'width': 28,
        'size': 73,
    }
    assert set(ds['image'].items()) >= set(expected.items())


def test_matplot_image(summary):
    img = plt.imshow(np.zeros((28, 28)), cmap='gray')
    summary["fig"] = img
    plt.close()
    ds = disk_summary(summary)
    assert os.path.exists(os.path.join(summary._run.dir, ds['fig']['path']))
    assert set(ds["fig"].items()) >= set({
        "_type": "image-file",
        "height": 480,
        "width": 640,
    }.items())


def test_matplot_plotly(summary):
    plt.cla()
    plt.plot([1, 2, 3])
    summary["plot"] = plt
    plt.close()
    plot = disk_summary(summary)["plot"]
    assert plot["_type"] == "plotly-file"


def test_plotly_plot(summary):
    scatter = go.Figure(  # plotly
        data=go.Scatter(x=[0, 1, 2]),
        layout=go.Layout(
            title=go.layout.Title(text="A Bar Chart")))
    summary["plot"] = scatter
    plot = disk_summary(summary)["plot"]
    assert plot["_type"] == "plotly-file"
    path = plot["path"]
    data = open(os.path.join(summary._run.dir, path)).read()
    plot_data = json.loads(data)
    assert plot_data["data"][0]['type'] == 'scatter'

def test_plotly_big_numpy(summary):
    N = 200
    x = np.arange(N)
    y = np.arange(0, N) / N
    scatter = go.Figure(  # plotly
        data=go.Scatter(x=[0, 1, 2]),
        layout=go.Layout(
            title=go.layout.Title(text="A Bar Chart")))
    summary["plot"] = scatter
    plot = disk_summary(summary)["plot"]
    path = plot["path"]
    data = open(os.path.join(summary._run.dir, path)).read()
    plot_data = json.loads(data)
    assert plot_data["data"][0]['type'] == 'scatter'

def test_graph(summary):
    graph = Graph()
    node_a = Node('a', 'Node A', size=(4,))
    node_b = Node('b', 'Node B', size=(16,))
    graph.add_node(node_a)
    graph.add_node(node_b)
    graph.add_edge(node_a, node_b)
    summary["graph"] = graph
    graph = disk_summary(summary)["graph"]
    path = graph["path"]
    data = open(os.path.join(summary._run.dir, path)).read()
    graph_data = json.loads(data)
    assert graph_data == {
        'edges': [['a', 'b']],
        'format': 'keras',
        'nodes': [{'id': 'a', 'name': 'Node A', 'size': [4]},
                  {'id': 'b', 'name': 'Node B', 'size': [16]}]}

def test_newline(summary):
    summary["rad \n"] = 1
    summary.update({"bad \n ": 2})
    summ = disk_summary(summary)
    assert summ["rad"] == 1
    assert summ["bad"] == 2


def test_big_numpy(summary):
    summary.update({"rad": np.random.rand(1000)})
    assert disk_summary(summary)["rad"]["max"] > 0
    assert os.path.exists(os.path.join(summary._run.dir, "wandb.h5"))


def test_big_nested_numpy(summary):
    summary.update({"rad": {"deep": np.random.rand(1000)}})
    assert disk_summary(summary)["rad"]["deep"]["max"] > 0
    summary["rad"]["deep2"] = np.random.rand(1000)
    assert disk_summary(summary)["rad"]["deep2"]["max"] > 0
    assert os.path.exists(os.path.join(summary._run.dir, "wandb.h5"))


def test_torch_tensor(summary):
    summary.update({"pytorch": torch.rand(1000, 1000)})
    assert os.path.exists(os.path.join(summary._run.dir, "wandb.h5"))
    assert disk_summary(summary)["pytorch"]["_type"] == "torch.Tensor"


def test_tensorflow_tensor(summary):
    with tf.Session().as_default():
        summary.update({"tensorflow": tf.random_normal([1000])})
    assert os.path.exists(os.path.join(summary._run.dir, "wandb.h5"))
    assert disk_summary(summary)["tensorflow"]["_type"] == "tensorflow.Tensor"


def test_pandas(summary):
    summary.update({"pandas": pandas.DataFrame(
        data=np.random.rand(1000), columns=['col'])})


def test_read_numpy(summary):
    summary.update({"rad": np.random.rand(1000)})
    s = FileSummary(summary._run)
    assert len(s["rad"]) == 1000


def test_read_nested_numpy(summary):
    summary.update({"rad": {"deep": np.random.rand(1000)}})
    s = FileSummary(summary._run)
    assert len(s["rad"]["deep"]) == 1000

def test_read_nested_array(summary):
    summary["rad"] = {"deep": "dish"}
    s = FileSummary(summary._run)
    assert summary["rad"]["deep"] == "dish"


def test_read_very_nested_numpy(summary):
    # Test that even deeply nested writes are written to disk.
    summary.update(
        {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {}}}}}}}}}})
    summary['a']['b']['c']['d']['e']['f']['g']['h']['i']['j'] = True
    assert disk_summary(summary)[
        'a']['b']['c']['d']['e']['f']['g']['h']['i']['j'] is True


def test_key_locking(summary):
    summary.update({'a': 'a'})
    assert summary['a'] == 'a'
    summary.update({'a': 'b'})
    assert summary['a'] == 'b'
    summary.update({'a': 'c'}, overwrite=False)
    assert summary['a'] == 'b'
