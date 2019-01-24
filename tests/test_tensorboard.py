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
    tf.summary.FileWriterCache.clear()
    summary = tf.summary.FileWriter(".")
    summary.add_summary(tf.Summary(
        value=[tf.Summary.Value(tag="foo", simple_value=1)]), 0)
    summary.flush()
    run_manager.test_shutdown()
    assert wandb.run.history.rows[0]["foo"] == 1.0
    assert wandb.run.history.rows[0]["global_step"] == 0
    assert len(glob.glob(wandb.run.dir + "/*tfevents*")) == 1


def test_tensorboard_s3(run_manager, capsys, mocker):
    # This mocks out the tensorboard writer so we dont attempt to talk to s3
    from tensorflow.python.summary.writer import event_file_writer

    def fake_init(self, logdir, **kwargs):
        writer = event_file_writer.EventFileWriter("test")
        mocker.patch.object(writer._ev_writer, "FileName",
                            lambda: logdir.encode("utf8"))
        mocker.patch.object(writer._ev_writer, "Flush")
        super(tf.summary.FileWriter, self).__init__(writer, None, None)
    mocker.patch("tensorflow.summary.FileWriter.__init__", fake_init)
    wandb.tensorboard.patch(tensorboardX=False)
    tf.summary.FileWriterCache.clear()
    summary = tf.summary.FileWriter("s3://simple/test")
    summary.add_summary(tf.Summary(
        value=[tf.Summary.Value(tag="foo", simple_value=1)]), 0)
    summary.flush()
    run_manager.test_shutdown()
    out, err = capsys.readouterr()
    assert "s3://simple/test" in err
    assert "can't save file to wandb" in err
    print(wandb.run.history.row)
    print(wandb.run.history.rows)
    assert wandb.run.history.rows[0]["foo"] == 1.0
    assert wandb.run.history.rows[0]["global_step"] == 0
    assert len(glob.glob(wandb.run.dir + "/*tfevents*")) == 0


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
