import pytest
import os
import json
import six
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import plotly.graph_objs as go
from click.testing import CliRunner

from wandb.history import History
from wandb import data_types
import torch
import tensorflow as tf

from . import utils


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
    history.add({"images": [data_types.Image(image)]})
    h = disk_history()
    assert h[0]["images"] == {'_type': 'images',
                              'count': 1, 'height': 28, 'width': 28}


def test_single_image(history):
    image = np.random.randint(255, size=(28, 28))
    history.add({"images": data_types.Image(image)})
    h = disk_history()
    assert h[0]["images"] == {'_type': 'images',
                              'count': 1, 'height': 28, 'width': 28}
    assert os.path.exists("media/images/images_0.jpg")


def test_newline(history):
    history.add({"wild_key \n": 10})
    h = disk_history()
    assert h[0]["wild_key"] == 10


def test_histogram(history):
    data = np.random.randint(255, size=500)
    history.add({"hist": data_types.Histogram(data)})
    h = disk_history()
    assert h[0]["hist"]['_type'] == 'histogram'
    assert len(h[0]["hist"]['values']) == 64


def test_matplotlib(history):
    plt.imshow(np.random.rand(28, 28), cmap='gray')
    history.add({"plt": plt})
    h = disk_history()
    assert h[0]["plt"] == {'_type': 'images',
                           'count': 1, 'height': 480, 'width': 640}


def test_table(history):
    history.add({"tbl": data_types.Table(
        rows=[["a", "b", "c"], ["d", "e", "f"]])})
    h = disk_history()
    assert h[0]["tbl"] == {'_type': 'table',
                           'columns': [u'Input', u'Output', u'Expected'],
                           'data': [[u'a', u'b', u'c'], [u'd', u'e', u'f']]}


def test_plotly(history):
    history.add({"plot": go.Scatter(x=[0, 1, 2])})
    plot = disk_history()[0]["plot"]
    assert plot["_type"] == "plotly"
    assert plot["plot"]['type'] == 'scatter'


def test_stream(history):
    history.stream("foo").add({"acc": 1})
    h = disk_history()
    assert di({"_stream": "foo", "acc": 1}) <= di(h[0])


def test_history_big_list(history):
    history.add({"boom": torch.randn(5, 7)})
    h = disk_history()
    assert h[0]["boom"]["_type"] == "histogram"


@pytest.mark.skipif(utils.PYTORCH_VERSION < (0, 4), reason='0d tensors not supported until 0.4')
def test_torch_single_in_log(history):
    history.add({
        "single_tensor": torch.tensor(0.63245),
    })
    h = disk_history()
    assert len(h) == 1
    assert round(h[0]["single_tensor"], 1) == 0.6


def test_torch_multi_in_log(history):
    history.add({
        "multi_tensor": utils.pytorch_tensor([0, 2, 3, 4])
    })
    h = disk_history()
    assert len(h) == 1
    assert h[0]["multi_tensor"] == [0, 2, 3, 4]


def test_tensorflow_in_log(history):
    single = tf.Variable(543.01, tf.float32)
    multi = tf.Variable([[2, 3], [7, 11]], tf.int32)
    with tf.Session().as_default() as sess:
        sess.run(tf.global_variables_initializer())
        history.add({
            "single": single,
            "multi": multi
        })
    h = disk_history()
    assert len(h) == 1
    assert round(h[0]["single"], 1) == 543.0
    assert h[0]["multi"] == [[2, 3], [7, 11]]


def test_log_blows_up(history):
    class Foo():
        def init(bar):
            self.bar = bar
    raised = False
    try:
        history.add({"foo": Foo("rad")})
    except:
        raised = True
    assert raised


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
