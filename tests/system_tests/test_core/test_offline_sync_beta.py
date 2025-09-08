from __future__ import annotations

import asyncio
import pathlib
import re
from typing import Callable

import pytest
import wandb
from click.testing import CliRunner
from typing_extensions import Any, TypeVar
from wandb.cli import beta_sync, cli
from wandb.proto import wandb_server_pb2 as spb
from wandb.proto import wandb_sync_pb2
from wandb.sdk import wandb_setup
from wandb.sdk.lib import asyncio_compat
from wandb.sdk.lib.printer import new_printer
from wandb.sdk.mailbox.mailbox import Mailbox
from wandb.sdk.mailbox.mailbox_handle import MailboxHandle

_T = TypeVar("_T")


class _Tester:
    """A fake ServiceConnection for async testing."""

    def __init__(self, mailbox: Mailbox) -> None:
        self._mailbox = mailbox

        self._cond = asyncio.Condition()
        self._init_sync_addrs: list[str] = []
        self._sync_addrs: list[str] = []
        self._sync_status_addrs: list[str] = []

    async def receive_init_sync(self) -> None:
        """Wait until an init_sync request."""
        await self._wait_for(self._init_sync_addrs)

    async def receive_sync(self) -> None:
        """Wait until a sync request."""
        await self._wait_for(self._sync_addrs)

    async def receive_sync_status(self) -> None:
        """Wait until a sync_status request."""
        await self._wait_for(self._sync_status_addrs)

    async def _wait_for(self, addrs: list[str]) -> None:
        async with self._cond:
            await asyncio.wait_for(
                self._cond.wait_for(lambda: bool(addrs)),
                timeout=5,
            )

    async def respond_init_sync(self, id: str) -> None:
        """Respond to an init_sync request."""
        resp = wandb_sync_pb2.ServerInitSyncResponse(id=id)
        await self._respond(self._init_sync_addrs, "init_sync_response", resp)

    async def respond_sync(self, errors: list[str]) -> None:
        """Respond to a sync request."""
        resp = wandb_sync_pb2.ServerSyncResponse(errors=errors)
        await self._respond(self._sync_addrs, "sync_response", resp)

    async def respond_sync_status(self, new_errors: list[str]) -> None:
        """Respond to a sync_status request."""
        resp = wandb_sync_pb2.ServerSyncStatusResponse(new_errors=new_errors)
        await self._respond(self._sync_status_addrs, "sync_status_response", resp)

    async def _respond(self, addrs: list[str], field: str, resp: Any) -> None:
        async with self._cond:
            await asyncio.wait_for(
                self._cond.wait_for(lambda: bool(addrs)),
                timeout=5,
            )
            addr = addrs.pop(0)

        server_response = spb.ServerResponse()
        server_response.request_id = addr
        getattr(server_response, field).CopyFrom(resp)

        await self._mailbox.deliver(server_response)

    def init_sync(
        self,
        paths: set[pathlib.Path],
        settings: wandb.Settings,
    ) -> MailboxHandle[wandb_sync_pb2.ServerInitSyncResponse]:
        return self._make_handle(
            self._init_sync_addrs,
            lambda r: r.init_sync_response,
        )

    def sync(self, id: str) -> MailboxHandle[wandb_sync_pb2.ServerSyncResponse]:
        return self._make_handle(
            self._sync_addrs,
            lambda r: r.sync_response,
        )

    def sync_status(
        self,
        id: str,
    ) -> MailboxHandle[wandb_sync_pb2.ServerSyncStatusResponse]:
        return self._make_handle(
            self._sync_status_addrs,
            lambda r: r.sync_status_response,
        )

    def _make_handle(
        self,
        addrs: list[str],
        to_response: Callable[[spb.ServerResponse], _T],
    ) -> MailboxHandle[_T]:
        req = spb.ServerRequest()
        handle = self._mailbox.require_response(req)

        async def update_addrs():
            async with self._cond:
                addrs.append(req.request_id)
                self._cond.notify_all()

        _ = asyncio.create_task(update_addrs())

        return handle.map(to_response)


@pytest.fixture
def skip_asyncio_sleep(monkeypatch):
    async def do_nothing(duration):
        pass

    monkeypatch.setattr(beta_sync, "_SLEEP", do_nothing)


def test_syncs_run(wandb_backend_spy, runner: CliRunner):
    with wandb.init(mode="offline") as run:
        run.log({"test_sync": 321})
        run.summary["test_sync_summary"] = "test summary"

    result = runner.invoke(cli.beta, f"sync {run.settings.sync_dir}")

    lines = result.output.splitlines()
    assert lines[0] == "Syncing 1 file(s):"
    assert lines[1].endswith(f"run-{run.id}.wandb")
    # More lines possible depending on status updates. Not deterministic.

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert len(history) == 1
        assert history[0]["test_sync"] == 321

        summary = snapshot.summary(run_id=run.id)
        assert summary["test_sync_summary"] == "test summary"


@pytest.mark.parametrize("skip_synced", (True, False))
def test_skip_synced(tmp_path, runner: CliRunner, skip_synced):
    (tmp_path / "run-1.wandb").touch()
    (tmp_path / "run-2.wandb").touch()
    (tmp_path / "run-2.wandb.synced").touch()
    (tmp_path / "run-3.wandb").touch()

    skip = "--skip-synced" if skip_synced else "--no-skip-synced"
    result = runner.invoke(cli.beta, f"sync --dry-run {skip} {tmp_path}")

    assert "run-1.wandb" in result.output
    assert "run-3.wandb" in result.output

    if skip_synced:
        assert "run-2.wandb" not in result.output
    else:
        assert "run-2.wandb" in result.output


def test_sync_wandb_file(tmp_path, runner: CliRunner):
    file = tmp_path / "run.wandb"
    file.touch()

    result = runner.invoke(cli.beta, f"sync --dry-run {file}")

    lines = result.output.splitlines()
    assert lines[0] == "Would sync 1 file(s):"
    assert lines[1].endswith("run.wandb")


def test_sync_run_directory(tmp_path, runner: CliRunner):
    run_dir = tmp_path / "some-run"
    run_dir.mkdir()
    (run_dir / "run.wandb").touch()

    result = runner.invoke(cli.beta, f"sync --dry-run {run_dir}")

    lines = result.output.splitlines()
    assert lines[0] == "Would sync 1 file(s):"
    assert lines[1].endswith("run.wandb")


def test_sync_wandb_directory(tmp_path, runner: CliRunner):
    wandb_dir = tmp_path / "wandb-dir"
    run1_dir = wandb_dir / "run-1"
    run2_dir = wandb_dir / "run-2"

    wandb_dir.mkdir()
    run1_dir.mkdir()
    run2_dir.mkdir()
    (run1_dir / "run-1.wandb").touch()
    (run2_dir / "run-2.wandb").touch()

    result = runner.invoke(cli.beta, f"sync --dry-run {wandb_dir}")

    lines = result.output.splitlines()
    assert lines[0] == "Would sync 2 file(s):"
    assert lines[1].endswith("run-1.wandb")
    assert lines[2].endswith("run-2.wandb")


def test_truncates_printed_paths(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
):
    monkeypatch.setattr(beta_sync, "_MAX_LIST_LINES", 5)
    files = list((tmp_path / f"run-{i}.wandb") for i in range(20))
    for file in files:
        file.touch()

    result = runner.invoke(cli.beta, f"sync --dry-run {tmp_path}")

    lines = result.output.splitlines()
    assert lines[0] == "Would sync 20 file(s):"
    for line in lines[1:6]:
        assert re.fullmatch(r"  .+/run-\d+\.wandb", line)
    assert lines[6] == "  +15 more"


def test_prints_status_updates(skip_asyncio_sleep, tmp_path, emulated_terminal):
    _ = skip_asyncio_sleep
    wandb_file = tmp_path / "run-test-progress.wandb"
    singleton = wandb_setup.singleton()
    mailbox = Mailbox(singleton.asyncer)

    async def simulate_service(tester: _Tester):
        await tester.respond_init_sync(id="sync-test")
        await tester.respond_sync_status(new_errors=["Err 1.", "Err 2."])
        await tester.receive_sync_status()

        assert emulated_terminal.read_stderr() == [
            "wandb: ERROR Err 1.",
            "wandb: ERROR Err 2.",
            "wandb: ⢿ Syncing...",
        ]

        await tester.respond_sync(errors=["Final error."])
        await tester.respond_sync_status(new_errors=[])

    async def do_test():
        tester = _Tester(mailbox=mailbox)

        async with asyncio_compat.open_task_group(exit_timeout=5) as group:
            group.start_soon(simulate_service(tester))
            group.start_soon(
                beta_sync._do_sync(
                    set([wandb_file]),
                    service=tester,  # type: ignore (we only mock used methods)
                    settings=wandb.Settings(),
                    printer=new_printer(),
                )
            )

        assert emulated_terminal.read_stderr() == [
            "wandb: ERROR Err 1.",
            "wandb: ERROR Err 2.",
            "wandb: ERROR Final error.",
        ]

    singleton.asyncer.run(do_test)
