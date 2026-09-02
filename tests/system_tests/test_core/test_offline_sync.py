import unittest.mock

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.lib.runid import generate_id


@pytest.mark.flaky
def test_sync_with_tensorboard(wandb_backend_spy, runner, copy_asset):
    run_id = generate_id()
    with unittest.mock.patch.dict("os.environ", {"WANDB_MODE": "offline"}):
        tf_event = copy_asset("events.out.tfevents.1585769947.cvp")
        result = runner.invoke(cli.sync, [tf_event, f"--id={run_id}"])
    assert result.exit_code == 0

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run_id)
        assert history[0]["_runtime"] == 0
        history_runtime_values = [v["_runtime"] for k, v in history.items() if k > 0]
        for value in history_runtime_values:
            assert value > 0


def test_legacy_sync_assigns_increasing_steps(wandb_backend_spy, runner):
    with wandb.init(mode="offline") as run:
        run.log({"loss": 0.1})
        run.log({"loss": 0.2})

    result = runner.invoke(cli.sync, [run.settings.sync_dir, "--legacy"])
    assert result.exit_code == 0

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert {row["_step"]: row["loss"] for row in history.values()} == {
            0: 0.1,
            1: 0.2,
        }


def test_legacy_sync_preserves_explicit_step(wandb_backend_spy, runner):
    with wandb.init(mode="offline") as run:
        run.log({"loss": 0.1}, step=7)

    result = runner.invoke(cli.sync, [run.settings.sync_dir, "--legacy"])
    assert result.exit_code == 0

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert len(history) == 1
        assert history[0]["_step"] == 7
        assert history[0]["loss"] == 0.1


def test_legacy_sync_append_renumbers_step_from_server_cursor(
    wandb_backend_spy,
    runner,
):
    """Legacy `--append` resumes against the server and writes at the next offset.

    This is the append behavior that has existed since PR #4848: `_setup_resume`
    sets the FileStream history offset so prior rows are preserved and the
    synced segment is appended rather than overwriting offset 0. Uses the real
    backend `RunResumeStatus` response (no stub).
    """
    with wandb.init() as run:
        run.log({"loss": 0.1}, step=0)
        run.log({"loss": 0.2}, step=1)
    run_id = run.id
    project = run.project
    entity = run.entity

    with wandb.init(mode="offline", id=run_id, project=project) as offline_run:
        offline_run.log({"loss": 0.4}, step=0)

    result = runner.invoke(
        cli.sync,
        [
            offline_run.settings.sync_dir,
            "--legacy",
            "--append",
            f"--entity={entity}",
            f"--project={project}",
        ],
    )
    assert result.exit_code == 0

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run_id)
        assert len(history) == 3
        assert history[0]["_step"] == 0
        assert history[0]["loss"] == 0.1
        assert history[1]["_step"] == 1
        assert history[1]["loss"] == 0.2
        assert history[2]["_step"] == 2
        assert history[2]["loss"] == 0.4
