import queue
import unittest.mock

import pytest
from wandb.cli import cli
from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.sdk.lib.runid import generate_id

from tests.fixtures.shared_run_log import (
    SHARED_SYNC_REJECTED_FRAGMENT,
    write_shared_run_log,
)


class _FakeSendManager:
    """Minimal SendManager stand-in so legacy sync can finish without blocking."""

    def __init__(self) -> None:
        self._record_q: queue.Queue = queue.Queue()
        self._result_q: queue.Queue = queue.Queue()

    def send(self, pb: wandb_internal_pb2.Record) -> None:
        if pb.WhichOneof("record_type") != "run":
            return
        result = wandb_internal_pb2.Result()
        result.run_result.run.run_id = pb.run.run_id
        result.run_result.run.entity = "test"
        result.run_result.run.project = "test"
        self._result_q.put(result)

    def finish(self) -> None:
        pass


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


def test_legacy_sync_rejects_shared_run(
    tmp_path,
    wandb_backend_spy,
    runner,
):
    run_dir = tmp_path / "offline-run-shared"
    wandb_file = run_dir / "run-shared.wandb"
    write_shared_run_log(wandb_file)

    result = runner.invoke(cli.sync, [str(wandb_file), "--legacy"])

    assert SHARED_SYNC_REJECTED_FRAGMENT in result.output
    with wandb_backend_spy.freeze() as snapshot:
        assert not snapshot.run_ids()


def test_legacy_sync_shared_run_with_override_skips_rejection(
    tmp_path,
    wandb_backend_spy,
    runner,
):
    run_dir = tmp_path / "offline-run-shared"
    wandb_file = run_dir / "run-shared.wandb"
    write_shared_run_log(wandb_file)

    with unittest.mock.patch(
        "wandb.sdk.internal.sender.SendManager.setup",
        return_value=_FakeSendManager(),
    ):
        result = runner.invoke(
            cli.sync,
            [str(wandb_file), "--legacy", "--include-shared"],
        )

    assert SHARED_SYNC_REJECTED_FRAGMENT not in result.output
    assert "duplicate metrics" in result.output
    assert "Syncing:" in result.output
