import matplotlib.pyplot as plt
plt.switch_backend('agg')

import sys
import os
import pytest
import glob
import json
import wandb
import numpy as np
import pytest
import tensorflow as tf
from tensorboardX import SummaryWriter

# Tests which rely on row history in memory should set `History.keep_rows = True`
from wandb.history import History
History.keep_rows = True


@pytest.mark.skipif(sys.version_info < (3, 6), reason="This test doesn't work in py2 tensorboard")
def test_tensorboard(run_manager):
    wandb.tensorboard.patch(tensorboardX=False, pytorch=False)
    tf.summary.FileWriterCache.clear()
    summary = tf.summary.FileWriter(".")
    summary.add_summary(tf.Summary(
        value=[tf.Summary.Value(tag="foo", simple_value=1)]), 0)
    summary.flush()
    run_manager.test_shutdown()
    print("Run History Rows", wandb.run.history.rows)
    assert wandb.run.history.rows[0]["foo"] == 1.0
    assert wandb.run.history.rows[0]["global_step"] == 0
    assert len(glob.glob(wandb.run.dir + "/*tfevents*")) == 1


@pytest.mark.skipif(sys.version_info < (3, 6), reason="This test doesn't work in py2 tensorboard")
def test_tensorboard_no_step(run_manager):
    wandb.tensorboard.patch(tensorboardX=False, pytorch=False)
    tf.summary.FileWriterCache.clear()
    summary = tf.summary.FileWriter(".")
    summary.add_summary(tf.Summary(
        value=[tf.Summary.Value(tag="foo", simple_value=1)]), 0)
    wandb.log({"foo": 10, "bar": 32})
    summary.add_summary(tf.Summary(
        value=[tf.Summary.Value(tag="foo", simple_value=2)]), 1)
    summary.flush()
    run_manager.test_shutdown()
    assert wandb.run.history.rows[1]["foo"] == 2
    assert wandb.run.history.rows[0]["bar"] == 32
    assert len(wandb.run.history.rows) == 2


@pytest.mark.mocked_run_manager()
def test_tensorboard_load_complex(wandb_init_run):
    """This test is to ensure the final event logged in a given step remains in that step"""
    steps_for_meta = []
    for summary in tf.train.summary_iterator(os.path.join(os.path.dirname(__file__),
                                                          "fixtures/events.out.tfevents.111.complex.localdomain")):
        parsed = wandb.tensorboard.tf_summary_to_dict(summary)
        if parsed.get("meta/activation/D/mean/high"):
            steps_for_meta.append(summary.step)
        wandb.tensorboard.log(summary, step=summary.step)
    wandb_init_run.run_manager.test_shutdown()
    rows = [json.loads(row) for row in open(os.path.join(wandb_init_run.dir, "wandb-history.jsonl")).readlines()]
    assert steps_for_meta == [row["global_step"] for row in rows if row.get("meta/activation/D/mean/high")]
    assert len(rows) == 43


@pytest.mark.mocked_run_manager()
def test_tensorboard_load_rate_limit_filter(wandb_init_run):
    """This test is to ensure the final event logged in a given step remains in that step"""
    try:
        wandb.tensorboard.configure(rate_limit_seconds=10, ignore_kinds=["histo"])
        for summary in tf.train.summary_iterator(os.path.join(os.path.dirname(__file__),
                                                              "fixtures/events.out.tfevents.111.complex.localdomain")):
            wandb.tensorboard.log(summary, step=summary.step)
        wandb_init_run.run_manager.test_shutdown()
        rows = [json.loads(row) for row in open(os.path.join(wandb_init_run.dir, "wandb-history.jsonl")).readlines()]
        assert len(rows) == 4
        assert rows[0].get("gradient/netG_A/norm/histogram") == None
    finally:
        wandb.tensorboard.configure()


@pytest.mark.skipif(sys.version_info < (3, 6), reason="This test doesn't work in py2 tensorboard")
def test_tensorboard_s3(run_manager, capsys, mocker):
    # This mocks out the tensorboard writer so we dont attempt to talk to s3
    from tensorflow.python.summary.writer import event_file_writer
    #from tensorboard.summary.writer import event_file_writer

    def fake_init(self, logdir, **kwargs):
        self._closed=False
        writer=event_file_writer.EventFileWriter("test")
        mocker.patch.object(writer._ev_writer, "FileName",
                            lambda: logdir.encode("utf8"))
        mocker.patch.object(writer._ev_writer, "Flush")
        super(tf.summary.FileWriter, self).__init__(writer, None, None)
    mocker.patch("tensorflow.summary.FileWriter.__init__", fake_init)
    wandb.tensorboard.patch(tensorboardX=False, pytorch=False)
    tf.summary.FileWriterCache.clear()
    summary=tf.summary.FileWriter("s3://simple/test")
    summary.add_summary(tf.Summary(
        value=[tf.Summary.Value(tag="foo", simple_value=1)]), 0)
    summary.flush()
    run_manager.test_shutdown()
    out, err=capsys.readouterr()
    print("OUT", out)
    print("ERR", err)
    assert "s3://simple/test" in err
    assert "can't save file to wandb" in err
    print(wandb.run.history.row)
    print(wandb.run.history.rows)
    assert wandb.run.history.rows[0]["foo"] == 1.0
    assert wandb.run.history.rows[0]["global_step"] == 0
    assert len(glob.glob(wandb.run.dir + "/*tfevents*")) == 0


@pytest.mark.skipif(sys.version_info < (3, 6), reason="No moviepy.editor in py2")
def test_tensorboardX(run_manager):
    wandb.tensorboard.patch(tensorboardX=True)

    fig=plt.figure()
    c1=plt.Circle((0.2, 0.5), 0.2, color='r')

    ax=plt.gca()
    ax.add_patch(c1)
    plt.axis('scaled')

    writer=SummaryWriter()
    writer.add_figure('matplotlib', fig, 0)
    writer.add_video('video', np.random.random(size=(1, 5, 3, 28, 28)), 0)
    writer.add_scalars('data/scalar_group', {
        'foo': 10,
        'bar': 100
    }, 1)
    writer.close()
    run_manager.test_shutdown()
    rows=run_manager.run.history.rows
    events=[]
    for root, dirs, files in os.walk(run_manager.run.dir):
        print("ROOT", root, files)
        for file in files:
            if "tfevent" in file:
                events.append(file)
    assert rows[0]["matplotlib"]['width'] == 640
    assert rows[0]["matplotlib"]['height'] == 480
    assert rows[0]["matplotlib"]['_type'] == 'images'
    assert rows[0]["video"]['_type'] == 'videos'
    assert rows[1]["data/scalar_group/foo"] == 10
    assert rows[1]["data/scalar_group/foo/global_step"] == 1
    assert rows[1]['data/scalar_group/bar'] == 100
    assert rows[1]['global_step'] == 1
    assert len(events) == 3
