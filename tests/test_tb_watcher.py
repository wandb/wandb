import os
import platform
import pytest
import re
import sys


PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    from wandb.sdk.internal import tb_watcher
else:
    from wandb.sdk_py27.internal import tb_watcher


class TestIsTfEventsFileCreatedBy:
    def test_simple(self):
        assert tb_watcher.is_tfevents_file_created_by(
            "out.writer.tfevents.193.me.94.5", "me", 193
        )

    def test_no_tfevents(self):
        assert (
            tb_watcher.is_tfevents_file_created_by(
                "out.writer.tfevent.193.me.94.5", "me", 193
            )
            is False
        )

    def test_short_prefix(self):
        assert (
            tb_watcher.is_tfevents_file_created_by("tfevents.193.me.94.5", "me", 193)
            is True
        )

    def test_too_early(self):
        assert (
            tb_watcher.is_tfevents_file_created_by("tfevents.192.me.94.5", "me", 193)
            is False
        )

    def test_dotted_hostname(self):
        assert (
            tb_watcher.is_tfevents_file_created_by(
                "tfevents.193.me.you.us.94.5", "me.you.us", 193
            )
            is True
        )

    def test_dotted_hostname_short(self):
        assert (
            tb_watcher.is_tfevents_file_created_by(
                "tfevents.193.me.you", "me.you.us", 193
            )
            is False
        )

    def test_invalid_time(self):
        assert (
            tb_watcher.is_tfevents_file_created_by(
                "tfevents.allo!.me.you", "me.you.us", 193
            )
            is False
        )

    def test_way_too_short(self):
        assert tb_watcher.is_tfevents_file_created_by("dir", "me.you.us", 193) is False

    def test_inverted(self):
        assert (
            tb_watcher.is_tfevents_file_created_by("me.193.tfevents", "me", 193)
            is False
        )


@pytest.mark.skipif(
    platform.system() == "Windows"
    or sys.version_info < (3, 5)
    or sys.version_info >= (3, 9),
    reason="TF has sketchy support for py2.  TODO: Windows is legitimately busted, tf not required for tests in py39",
)
def test_tb_watcher_save_row_custom_chart(mocked_run, tbwatcher_util):
    pytest.importorskip("tensorboard.summary.v1")
    import tensorboard.summary.v1 as tb_summary
    import tensorflow as tf

    def write_fun():
        writer = tf.summary.create_file_writer(mocked_run.dir)
        pr_curve_summary = tb_summary.pr_curve(
            "pr",
            labels=tf.constant([True, False, True]),
            predictions=tf.constant([0.7, 0.2, 0.3]),
            num_thresholds=5,
        )

        with writer.as_default():
            tf.summary.experimental.write_raw_pb(pr_curve_summary, step=0)
        writer.close()

    ctx_util = tbwatcher_util(
        write_function=write_fun,
        logdir=mocked_run.dir,
        save=False,
        root_dir=mocked_run.dir,
    )
    assert "visualize" in [k for k in ctx_util.config["_wandb"]["value"].keys()]
    assert "pr/pr_curves" in [
        k for k in ctx_util.config["_wandb"]["value"]["visualize"].keys()
    ]


def test_tb_watcher_logdir_not_exists(mocked_run, tbwatcher_util, capsys):
    # TODO: check caplog for right error text
    pytest.importorskip("tensorboard.summary.v1")
    import tensorboard.summary.v1 as tb_summary

    log_dir = os.path.join(mocked_run.dir, "test_tb_dne_dir")

    def write_fun():
        pass

    _ = tbwatcher_util(
        write_function=write_fun, logdir=log_dir, save=False, root_dir=mocked_run.dir,
    )
    _, err = capsys.readouterr()
    assert err == ""
