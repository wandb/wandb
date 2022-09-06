import platform
from unittest import mock

import numpy as np
import pytest
import wandb


def test_big_table_throws_error_that_can_be_overridden(wandb_init):
    run = wandb_init(settings={"table_raise_on_max_row_limit_exceeded": True})

    # make this smaller just for this one test to make the runtime shorter
    with mock.patch("wandb.Table.MAX_ARTIFACT_ROWS", 10):
        table = wandb.Table(
            data=np.arange(wandb.Table.MAX_ARTIFACT_ROWS + 1)[:, None].tolist(),
            columns=["col1"],
        )

        with pytest.raises(ValueError):
            run.log({"table": table})

        with mock.patch(
            "wandb.Table.MAX_ARTIFACT_ROWS", wandb.Table.MAX_ARTIFACT_ROWS + 1
        ):
            try:
                # should no longer raise
                run.log({"table": table})
            except Exception as e:
                raise AssertionError(
                    f"Logging a big table with an overridden limit raised with {e}"
                )

        run.finish()


def test_table_logging(
    wandb_init,
):  # TODO: do we need this fixture? reinit_internal_api
    run = wandb_init()
    run.log(
        {
            "logged_table": wandb.Table(
                columns=["a"],
                data=[[wandb.Image(np.ones(shape=(32, 32)))]],
            )
        }
    )
    run.finish()
    assert True


def test_partitioned_table_logging(wandb_init):
    run = wandb_init()
    run.log({"logged_table": wandb.data_types.PartitionedTable("parts")})
    run.finish()
    assert True


def test_joined_table_logging(wandb_init):
    run = wandb_init()
    art = wandb.Artifact("A", "dataset")
    t1 = wandb.Table(
        columns=["id", "a"],
        data=[[1, wandb.Image(np.ones(shape=(32, 32)))]],
    )
    t2 = wandb.Table(
        columns=["id", "a"],
        data=[[1, wandb.Image(np.ones(shape=(32, 32)))]],
    )
    art.add(t1, "t1")
    art.add(t2, "t2")
    jt = wandb.JoinedTable(t1, t2, "id")
    art.add(jt, "jt")
    run.log_artifact(art)
    run.log({"logged_table": jt})
    run.finish()
    assert True


# @pytest.mark.skip(reason="Currently seems to fail in CI")
def test_log_with_dir_sep_windows(wandb_init):
    image = np.zeros((28, 28))
    run = wandb_init()
    wb_image = wandb.Image(image)
    run.log({"train/image": wb_image})
    run.finish()
    assert True


# @pytest.mark.skip(reason="Currently seems to fail in CI")
def test_log_with_back_slash_windows(wandb_init):
    run = wandb_init()
    wb_image = wandb.Image(np.zeros((28, 28)))

    # windows doesnt allow a backslash in media keys right now
    if platform.system() == "Windows":
        with pytest.raises(ValueError):
            run.log({r"train\image": wb_image})
    else:
        run.log({r"train\image": wb_image})

    run.finish()
    assert True


def test_image_array_old_wandb(relay_server, wandb_init, monkeypatch, capsys):
    with relay_server() as relay:
        monkeypatch.setattr(wandb.util, "_get_max_cli_version", lambda: "0.10.33")
        run = wandb_init()
        wb_image = [wandb.Image(np.zeros((28, 28))) for i in range(5)]
        run.log({"logged_images": wb_image})
        run.finish()
        outerr = capsys.readouterr()

        assert "Unable to log image array filenames." in outerr.err

        assert "filenames" not in relay.context.summary["logged_images"][0]


def test_image_array_old_wandb_mp_warning(wandb_init, capsys, monkeypatch):
    monkeypatch.setattr(wandb.util, "_get_max_cli_version", lambda: "0.10.33")
    with mock.patch.dict("os.environ", WANDB_REQUIRE_SERVICE="true"):
        run = wandb_init()
        wb_image = [wandb.Image(np.zeros((28, 28))) for _ in range(5)]
        run._init_pid += 1
        run.log({"logged_images": wb_image})
        run.finish()
    outerr = capsys.readouterr()
    assert (
        "Attempting to log a sequence of Image objects from multiple processes might result in data loss. Please upgrade your wandb server"
        in outerr.err
    )
