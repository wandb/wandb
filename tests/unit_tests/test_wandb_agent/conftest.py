"""Fixtures and helpers for sweep agent unit tests."""

from __future__ import annotations

import contextlib
import dataclasses
import multiprocessing
import queue
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
import wandb
import wandb.agents.pyagent as pyagent
from wandb.proto import wandb_api_pb2
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.wandb_agent import Agent as CliAgent

DEFAULT_AGENT_ID = "test-agent"
DEFAULT_SWEEP_ID = "sweep-test"
DEFAULT_CLI_SWEEP_ID = "sweep-cli-test"
DEFAULT_ENTITY = "test-entity"
DEFAULT_PROJECT = "test-project"


def heartbeat_run_command(
    run_id: str,
    args: dict[str, dict[str, Any]],
    program: str = "train.py",
) -> dict[str, Any]:
    """Build a heartbeat `run` command for sweep agent tests."""
    return {
        "type": "run",
        "run_id": run_id,
        "args": args,
        "program": program,
    }


def sequence_heartbeat_responses(
    *responses: list[dict[str, Any]] | BaseException,
) -> Callable[..., list[dict[str, Any]]]:
    """Return an `agent_heartbeat` side effect that yields each response in order."""
    pending = list(responses)

    def side_effect(agent_id, metrics, run_states):
        if not pending:
            return []
        response = pending.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    return side_effect


def sweep_not_running_api_error(
    sweep_id: str = DEFAULT_SWEEP_ID,
) -> WandbApiFailedError:
    """Build the 400 error `createAgent` returns for a terminal-state sweep."""
    message = f"Sweep {sweep_id} is not running"
    return WandbApiFailedError(
        message,
        response=wandb_api_pb2.ApiErrorResponse(message=message, http_status=400),
    )


@dataclasses.dataclass
class WandbAgentTestEnv:
    """Pytest-friendly harness for mocked sweep-agent unit tests."""

    monkeypatch: pytest.MonkeyPatch
    tmp_path: Path
    sweep_id: str = DEFAULT_SWEEP_ID
    cli_sweep_id: str = DEFAULT_CLI_SWEEP_ID
    entity: str = DEFAULT_ENTITY
    project: str = DEFAULT_PROJECT

    def mock_api(
        self, *, for_cli: bool = False, agent_id: str = DEFAULT_AGENT_ID
    ) -> mock.MagicMock:
        """Return a mock API with agent registration stubbed out."""
        api = mock.MagicMock()
        api.register_agent.return_value = {"id": agent_id}
        if for_cli:
            api.sweep.return_value = None
        self.patch_sweep_helpers("wandb.wandb_agent", api)
        self.patch_sweep_helpers("wandb.agents.pyagent", api)
        return api

    def patch_sweep_helpers(self, module: str, api: mock.MagicMock) -> None:
        """Route the module's sweep API helpers to the mock API's methods."""
        self.monkeypatch.setattr(wandb, "Api", lambda *args, **kwargs: api)
        for helper, method in [
            ("_sweep_with_runs", api.sweep),
            ("_register_agent", api.register_agent),
            ("_agent_heartbeat", api.agent_heartbeat),
        ]:
            self.monkeypatch.setattr(
                f"{module}.{helper}",
                lambda _api, *args, _method=method, **kwargs: _method(*args, **kwargs),
                raising=False,
            )

    def patch_cli(self, sweep_id: str | None = None) -> None:
        """Avoid slow queue reads and noisy teardown when unit-testing CLI agents."""
        sweep_id = sweep_id or self.cli_sweep_id
        self.monkeypatch.chdir(self.tmp_path)
        self.monkeypatch.setenv(wandb.env.SWEEP_ID, sweep_id)
        self.monkeypatch.setenv(wandb.env.DIR, str(self.tmp_path))
        self.monkeypatch.setattr(
            "wandb.wandb_agent.util.read_many_from_queue",
            lambda q, max_items, queue_timeout: [],
        )
        self.monkeypatch.setattr(wandb, "teardown", lambda *args, **kwargs: None)

    @contextlib.contextmanager
    def patch_pyagent(
        self,
        api: mock.MagicMock,
        *,
        mock_finish: bool = True,
    ) -> Iterator[None]:
        """Apply pyagent env isolation for an agent run."""
        self.monkeypatch.chdir(self.tmp_path)
        self.monkeypatch.setenv(wandb.env.DIR, str(self.tmp_path))
        if mock_finish:
            self.monkeypatch.setattr(wandb, "teardown", lambda *args, **kwargs: None)
            self.monkeypatch.setattr(wandb, "finish", lambda *args, **kwargs: None)

        original_queue_get = queue.Queue.get

        def fast_queue_get(self, block=True, timeout=None):
            if timeout is not None and timeout > 0.1:
                timeout = 0.01
            return original_queue_get(self, block=block, timeout=timeout)

        self.monkeypatch.setattr(queue.Queue, "get", fast_queue_get)

        yield

    def make_pyagent(
        self,
        function: Callable[[], Any],
        *,
        count: int = 1,
        sweep_id: str | None = None,
        entity: str | None = None,
        project: str | None = None,
    ) -> pyagent.Agent:
        """Build an in-process sweep agent for unit tests."""
        return pyagent.Agent(
            sweep_id=sweep_id or self.sweep_id,
            function=function,
            entity=entity or self.entity,
            project=project or self.project,
            count=count,
        )

    def make_cli_agent(
        self,
        api: mock.MagicMock,
        *,
        sweep_id: str | None = None,
        function: Callable[[], Any] | None = None,
        count: int | None = None,
    ) -> CliAgent:
        """Build a CLI subprocess sweep agent for unit tests."""
        return CliAgent(
            api,
            multiprocessing.Queue(),
            sweep_id=sweep_id or self.cli_sweep_id,
            function=function,
            in_jupyter=False,
            count=count,
        )

    def run_pyagent(
        self,
        api: mock.MagicMock,
        function: Callable[[], Any],
        *,
        count: int = 1,
        sweep_id: str | None = None,
        entity: str | None = None,
        project: str | None = None,
        mock_finish: bool = True,
    ) -> None:
        """Run a single mocked in-process sweep agent to completion."""
        with self.patch_pyagent(api, mock_finish=mock_finish):
            self.make_pyagent(
                function,
                count=count,
                sweep_id=sweep_id,
                entity=entity,
                project=project,
            ).run()

    def run_cli_agent(
        self,
        api: mock.MagicMock,
        *,
        sweep_id: str | None = None,
        count: int | None = None,
    ) -> None:
        """Run a single mocked CLI sweep agent to completion."""
        self.patch_cli(sweep_id=sweep_id)
        self.make_cli_agent(api, sweep_id=sweep_id, count=count).run()


@pytest.fixture(autouse=True)
def _wandb_agent_base_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patches shared by all sweep-agent unit tests in this package."""
    monkeypatch.setattr("wandb.sdk.wandb_login._login", lambda *args, **kwargs: None)
    monkeypatch.setattr(pyagent.Agent, "HEARTBEAT_SLEEP_SECONDS", 0.05)
    monkeypatch.setattr("wandb.agents.pyagent.time.sleep", lambda *args, **kwargs: None)


@pytest.fixture
def wandb_agent_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> WandbAgentTestEnv:
    """Isolated sweep-agent test harness with mocked API and no login."""
    return WandbAgentTestEnv(monkeypatch=monkeypatch, tmp_path=tmp_path)
