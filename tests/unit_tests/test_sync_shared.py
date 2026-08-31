"""Tests for rejecting shared-mode runs during legacy wandb sync."""

import queue
import unittest.mock

import pytest
from wandb.cli import cli
from wandb.proto import wandb_internal_pb2  # type: ignore

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


@pytest.fixture
def authenticated_sync_api(monkeypatch: pytest.MonkeyPatch) -> unittest.mock.MagicMock:
    api = unittest.mock.MagicMock()
    api.is_authenticated = True
    api.app_url = "https://app.test"
    monkeypatch.setattr("wandb.cli.cli._get_cling_api", lambda reset=None: api)
    return api


@pytest.mark.usefixtures("patch_max_cli_version", "authenticated_sync_api")
def test_legacy_sync_rejects_shared_run(
    tmp_path,
    runner,
):
    run_dir = tmp_path / "offline-run-shared"
    wandb_file = run_dir / "run-shared.wandb"
    write_shared_run_log(wandb_file)

    result = runner.invoke(cli.sync, [str(wandb_file), "--legacy"])

    assert SHARED_SYNC_REJECTED_FRAGMENT in result.output


@pytest.mark.usefixtures("patch_max_cli_version", "authenticated_sync_api")
def test_legacy_sync_shared_run_with_override_skips_rejection(
    tmp_path,
    runner,
):
    run_dir = tmp_path / "offline-run-shared"
    wandb_file = run_dir / "run-shared.wandb"
    write_shared_run_log(wandb_file)

    with unittest.mock.patch(
        "wandb.sync.sync.sender.SendManager.setup",
        return_value=_FakeSendManager(),
    ):
        result = runner.invoke(
            cli.sync,
            [str(wandb_file), "--legacy", "--include-shared"],
        )

    assert SHARED_SYNC_REJECTED_FRAGMENT not in result.output
    assert "duplicate metrics" in result.output
    assert "Syncing:" in result.output
