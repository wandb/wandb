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
from wandb.sdk.lib import asyncio_compat, wbauth
from wandb.sdk.lib.printer import new_printer
from wandb.sdk.mailbox.mailbox import Mailbox
from wandb.sdk.mailbox.mailbox_handle import MailboxHandle

from tests.fixtures.emulated_terminal import EmulatedTerminal
from tests.fixtures.wandb_backend_spy import WandbBackendSpy

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

    async def respond_sync(
        self,
        infos: list[str],
        errors: list[str],
    ) -> None:
        """Respond to a sync request."""
        resp = wandb_sync_pb2.ServerSyncResponse(
            messages=self._to_messages(infos=infos, errors=errors),
        )
        await self._respond(self._sync_addrs, "sync_response", resp)

    async def respond_sync_status(
        self,
        new_infos: list[str],
        new_errors: list[str],
    ) -> None:
        """Respond to a sync_status request."""
        resp = wandb_sync_pb2.ServerSyncStatusResponse(
            new_messages=self._to_messages(infos=new_infos, errors=new_errors),
        )
        await self._respond(self._sync_status_addrs, "sync_status_response", resp)

    def _to_messages(
        self,
        infos: list[str],
        errors: list[str],
    ) -> list[wandb_sync_pb2.ServerSyncMessage]:
        messages: list[wandb_sync_pb2.ServerSyncMessage] = []

        for info in infos:
            messages.append(
                wandb_sync_pb2.ServerSyncMessage(
                    severity=wandb_sync_pb2.ServerSyncMessage.SEVERITY_INFO,
                    content=info,
                )
            )
        for error in errors:
            messages.append(
                wandb_sync_pb2.ServerSyncMessage(
                    severity=wandb_sync_pb2.ServerSyncMessage.SEVERITY_ERROR,
                    content=error,
                )
            )

        return messages

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

    async def init_sync(
        self,
        paths: set[pathlib.Path],
        settings: wandb.Settings,
        *,
        cwd: pathlib.Path | None,
        live: bool,
        entity: str,
        project: str,
        run_id: str,
    ) -> MailboxHandle[wandb_sync_pb2.ServerInitSyncResponse]:
        _, _, _, _, _, _, _ = paths, settings, cwd, live, entity, project, run_id
        return await self._make_handle(
            self._init_sync_addrs,
            lambda r: r.init_sync_response,
        )

    async def sync(
        self,
        id: str,
        parallelism: int,
    ) -> MailboxHandle[wandb_sync_pb2.ServerSyncResponse]:
        _, _ = id, parallelism
        return await self._make_handle(
            self._sync_addrs,
            lambda r: r.sync_response,
        )

    async def sync_status(
        self,
        id: str,
    ) -> MailboxHandle[wandb_sync_pb2.ServerSyncStatusResponse]:
        _ = id
        return await self._make_handle(
            self._sync_status_addrs,
            lambda r: r.sync_status_response,
        )

    async def _make_handle(
        self,
        addrs: list[str],
        to_response: Callable[[spb.ServerResponse], _T],
    ) -> MailboxHandle[_T]:
        req = spb.ServerRequest()
        handle = self._mailbox.require_response(req)

        async with self._cond:
            addrs.append(req.request_id)
            self._cond.notify_all()

        return handle.map(to_response)


@pytest.fixture
def skip_asyncio_sleep(monkeypatch: pytest.MonkeyPatch):
    async def do_nothing(duration: float) -> None:
        _ = duration

    monkeypatch.setattr(beta_sync, "_SLEEP", do_nothing)


def _unauthenticate_for_test() -> None:
    """Clear auth to verify that syncing explicitly authenticates."""
    wbauth.unauthenticate_session(update_settings=True)


def test_syncs_run(
    tmp_path: pathlib.Path,
    wandb_backend_spy: WandbBackendSpy,
    runner: CliRunner,
):
    _unauthenticate_for_test()
    test_file = tmp_path / "test_file.txt"
    test_file.touch()

    with wandb.init(mode="offline") as run:
        run.log({"test_sync": 321})
        run.save(test_file, base_path=test_file.parent)
        run.summary["test_sync_summary"] = "test summary"

    result = runner.invoke(cli.beta, f"sync {run.settings.sync_dir}")

    lines = result.output.splitlines()
    assert lines[0] == "wandb: Syncing 1 run(s):"
    assert lines[1].endswith(f"run-{run.id}.wandb")
    # More lines possible depending on status updates. Not deterministic.
    assert lines[-1].startswith(f"wandb: [{run.path}] Finished syncing")

    synced_file = pathlib.Path(run.settings.sync_file + ".synced")
    assert synced_file.exists()

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert len(history) == 1
        assert history[0]["test_sync"] == 321

        summary = snapshot.summary(run_id=run.id)
        assert summary["test_sync_summary"] == "test summary"

        files = snapshot.uploaded_files(run_id=run.id)
        assert "test_file.txt" in files


def test_sync_defaults_to_wandb_dir(tmp_path: pathlib.Path, runner: CliRunner):
    global_settings = wandb_setup.singleton().settings
    global_settings.root_dir = str(tmp_path)
    wandb_dir = pathlib.Path(global_settings.wandb_dir)
    paths = [wandb_dir / f"offline-run-{i}" / f"run-{i}.wandb" for i in range(5)]
    for path in paths:
        path.parent.mkdir(parents=True)
        path.touch()

    result = runner.invoke(cli.beta, "sync", input="n")

    assert result.output.splitlines() == [
        "wandb: Syncing 5 run(s):",
        f"wandb:   {paths[0]}",
        f"wandb:   {paths[1]}",
        f"wandb:   {paths[2]}",
        f"wandb:   {paths[3]}",
        f"wandb:   {paths[4]}",
        "wandb: Sync the listed runs? [y/n] n",
    ]


def test_syncs_resumed_run(
    wandb_backend_spy: WandbBackendSpy,
    runner: CliRunner,
):
    with wandb.init() as run1:
        run1.log({"x": "a"})
    with wandb.init(id=run1.id, resume="must") as run2:
        run2.log({"x": "b"})
    with wandb.init(id=run1.id, resume="must") as run3:
        run3.log({"x": "c"})
    run1_dir = run1.settings.sync_dir
    run2_dir = run2.settings.sync_dir
    run3_dir = run3.settings.sync_dir
    new_id = f"{run1.id}-copy"

    runner.invoke(cli.beta, f"sync --id {new_id} {run3_dir} {run1_dir} {run2_dir}")

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=new_id)
        xs = {n: history[n]["x"] for n in history}

        # Asynchrony in the backend sometimes causes it to return an old step
        # when resuming, making the SDK overwrite that step. So, for instance,
        # this could be {0: "a", 1: "c"} or {0: "b", 1: "c"}.
        #
        # When running this test 100 times on 14 pytest workers reusing the
        # same local-testcontainer, the test flaked once for me.
        assert xs == {0: "a", 1: "b", 2: "c"}


def test_sync_to_other_path(
    wandb_backend_spy: WandbBackendSpy,
    runner: CliRunner,
):
    # It is too cumbersome to change the run's entity in this test
    # as it requires creating a new user, so we only test changing
    # the project and ID.
    with wandb.init(mode="offline", project="project1") as run:
        run.log({"x": 1})

    runner.invoke(
        cli.beta,
        f"sync -p project2 --id {run.id}-copy {run.settings.sync_dir}",
    )

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(
            run_id=f"{run.id}-copy",
            project="project2",
        )

        assert len(history) == 1
        assert history[0]["x"] == 1


@pytest.mark.parametrize("skip_synced", (True, False))
def test_skip_synced(
    tmp_path: pathlib.Path,
    runner: CliRunner,
    skip_synced: bool,
):
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


def test_merges_symlinks(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
):
    (tmp_path / "actual-run").mkdir()
    (tmp_path / "actual-run/run.wandb").touch()
    (tmp_path / "latest-run").symlink_to(tmp_path / "actual-run")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.beta, "sync --dry-run .")

    assert result.output.splitlines() == [
        "wandb: Would sync 1 run(s):",
        "wandb:   actual-run/run.wandb",
    ]


def test_sync_wandb_file(tmp_path: pathlib.Path, runner: CliRunner):
    file = tmp_path / "run.wandb"
    file.touch()

    result = runner.invoke(cli.beta, f"sync --dry-run {file}")

    lines = result.output.splitlines()
    assert lines[0] == "wandb: Would sync 1 run(s):"
    assert lines[1].endswith("run.wandb")


def test_sync_run_directory(tmp_path: pathlib.Path, runner: CliRunner):
    run_dir = tmp_path / "some-run"
    run_dir.mkdir()
    (run_dir / "run.wandb").touch()

    result = runner.invoke(cli.beta, f"sync --dry-run {run_dir}")

    lines = result.output.splitlines()
    assert lines[0] == "wandb: Would sync 1 run(s):"
    assert lines[1].endswith("run.wandb")


def test_sync_wandb_directory(tmp_path: pathlib.Path, runner: CliRunner):
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
    assert lines[0] == "wandb: Would sync 2 run(s):"
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
    assert lines[0] == "wandb: Would sync 20 run(s):"
    for line in lines[1:6]:
        assert re.fullmatch(r"wandb:   .+/run-\d+\.wandb", line)
    assert lines[6] == "wandb:   +15 more (pass --verbose to see all)"


def test_prints_relative_paths(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
):
    dir1_cwd = tmp_path / "cwd"
    dir2_not = tmp_path / "not"
    dir1_cwd.mkdir()
    dir2_not.mkdir()
    monkeypatch.chdir(dir1_cwd)

    (dir1_cwd / "run-relative.wandb").touch()
    (dir2_not / "run-absolute.wandb").touch()

    result = runner.invoke(cli.beta, f"sync --dry-run {tmp_path}")

    assert result.output.splitlines() == [
        "wandb: Would sync 2 run(s):",
        *sorted(
            [
                "wandb:   run-relative.wandb",
                f"wandb:   {dir2_not / 'run-absolute.wandb'}",
            ]
        ),
    ]


@pytest.mark.usefixtures("skip_asyncio_sleep")
def test_prints_status_updates(
    tmp_path: pathlib.Path,
    emulated_terminal: EmulatedTerminal,
):
    async def cancel_noop(id: str) -> None:
        _ = id

    wandb_file = tmp_path / "run-test-progress.wandb"
    singleton = wandb_setup.singleton()
    mailbox = Mailbox(singleton.asyncer, cancel_noop)

    async def simulate_service(tester: _Tester):
        await tester.respond_init_sync(id="sync-test")
        await tester.respond_sync_status(
            new_infos=["Msg 1.", "Msg 2."],
            new_errors=["Err 1.", "Err 2."],
        )
        await tester.receive_sync_status()

        assert emulated_terminal.read_stderr() == [
            "wandb: Msg 1.",
            "wandb: Msg 2.",
            "wandb: ERROR Err 1.",
            "wandb: ERROR Err 2.",
            "wandb: ⢿ Syncing...",
        ]

        await tester.respond_sync(
            infos=["Final message."],
            errors=["Final error."],
        )
        await tester.respond_sync_status(new_infos=[], new_errors=[])

    async def do_test():
        tester: Any = _Tester(mailbox=mailbox)

        async with asyncio_compat.open_task_group(exit_timeout=5) as group:
            group.start_soon(simulate_service(tester))
            group.start_soon(
                beta_sync._do_sync(
                    set([wandb_file]),
                    cwd=None,
                    live=False,
                    service=tester,  # type: ignore (we only mock used methods)
                    entity="",
                    project="",
                    run_id="",
                    settings=wandb.Settings(),
                    printer=new_printer(),
                    parallelism=1,
                )
            )

        assert emulated_terminal.read_stderr() == [
            "wandb: Msg 1.",
            "wandb: Msg 2.",
            "wandb: ERROR Err 1.",
            "wandb: ERROR Err 2.",
            "wandb: Final message.",
            "wandb: ERROR Final error.",
        ]

    singleton.asyncer.run(do_test)
