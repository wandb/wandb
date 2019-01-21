import matplotlib.pyplot as plt
plt.switch_backend('agg')
from tensorboardX import SummaryWriter
import tensorflow as tf
import wandb
import glob
import pytest
import os
import sys


def test_tensorboard(run_manager):
    wandb.tensorboard.patch(tensorboardX=False)
    summary = tf.summary.FileWriter(".")
    summary.add_summary(tf.Summary(
        value=[tf.Summary.Value(tag="foo", simple_value=1)]), 0)
    summary.flush()
    run_manager.test_shutdown()
    assert wandb.run.history.rows[0]["foo"] == 1.0
    assert wandb.run.history.rows[0]["global_step"] == 0
    assert len(glob.glob(wandb.run.dir + "/*tfevents*")) == 1


def test_tensorboardX(run_manager):
    wandb.tensorboard.patch(tensorboardX=True)

    fig = plt.figure()
    c1 = plt.Circle((0.2, 0.5), 0.2, color='r')

    ax = plt.gca()
    ax.add_patch(c1)
    plt.axis('scaled')

    writer = SummaryWriter()
    writer.add_figure('matplotlib', fig, 0)
    writer.add_scalars('data/scalar_group', {
        'foo': 10,
        'bar': 100
    }, 1)
    writer.close()
    run_manager.test_shutdown()
    rows = run_manager.run.history.rows
    events = []
    for root, dirs, files in os.walk(run_manager.run.dir):
        for file in files:
            if "tfevent" in file:
                events.append(file)
    assert rows[0]["matplotlib"] == {
        "width": 640, "height": 480, "count": 1, "_type": "images"}
    assert rows[1]["data/scalar_group/foo"] == 10
    assert rows[1]["data/scalar_group/bar"] == 100
    assert len(events) == 3
