import os
import platform

import pytest


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="TODO: Windows is legitimately busted",
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
        write_function=write_fun,
        logdir=log_dir,
        save=False,
        root_dir=mocked_run.dir,
    )
    _, err = capsys.readouterr()
    assert err == ""
