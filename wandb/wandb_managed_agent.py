"""Managed sweep agents that run inside W&B (Aviato) sandboxes.

``ManagedAgent`` configures an Aviato sandbox to download artifact code and
run ``wandb agent``.  The sandbox keeps alive via ``sleep infinity``; the
agent startup script runs via ``sandbox.exec()``.

``ManagedAgentSession`` manages a pool of such sandboxes.  Completion is
monitored with ``concurrent.futures.wait()`` — the Python equivalent of
``select(2)`` — so there is **no per-sandbox monitor thread**.  Output is
printed per-sandbox in docker-compose style after each exec completes.

Thread budget for N parallel agents: 1 background executor thread (shared
by the sandbox library) + main thread in ``concurrent.futures.wait()``.

The session configuration is modelled after SkyPilot's task-YAML schema.

Quick start::

    import wandb
    from wandb.wandb_managed_agent import ManagedAgentSession, ManagedAgentSessionConfig

    cfg = ManagedAgentSessionConfig.from_yaml("sweep_session.yaml")
    with ManagedAgentSession(cfg) as session:
        session.run()

YAML example (``sweep_session.yaml``)::

    sweep_id: abc123
    entity: acme
    project: mnist
    artifact_id: acme/mnist/training-code:latest
    num_agents: 4
    container_image: pytorch/pytorch:2.0.0-cuda11.7-cudnn8-runtime
    resources:
      accelerators: A100:1
      cpus: 8
      memory: 32
    envs:
      DATA_PATH: /data/mnist
"""

from __future__ import annotations

import concurrent.futures
import logging
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple

import yaml

import wandb
from wandb.apis import InternalApi

if TYPE_CHECKING:
    from sandbox import AviatoSandbox, Environment
    from sandbox.future import SandboxFuture
    from sandbox.protocol import ExecResult

logger = logging.getLogger(__name__)

_ARTIFACT_SANDBOX_ROOT = "/app"

# ANSI colours for docker-compose-style log prefixes.
_LABEL_COLOURS = [
    "\033[36m",  # cyan
    "\033[32m",  # green
    "\033[33m",  # yellow
    "\033[35m",  # magenta
    "\033[34m",  # blue
    "\033[31m",  # red
]
_RESET = "\033[0m"

# One week — long enough for any realistic sweep run.
_DEFAULT_EXEC_TIMEOUT_SECONDS = 86400 * 7


# ──────────────────────────────────────────────────────────────────────────────
# Configuration dataclasses  (SkyPilot-inspired declarative schema)
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class SandboxResources:
    """Hardware resource request for a sandbox.

    Mirrors SkyPilot's ``Resources`` spec so teams can reuse the same mental
    model across cloud VMs and sandboxes.

    ``accelerators`` accepts SkyPilot shorthand: ``"A100:1"``, ``"H100:4"``,
    or a bare type string ``"A100"`` (implies 1).  A dict form is also
    accepted: ``{"A100": 1}``.
    """

    accelerators: str | dict[str, int] | None = None
    cpus: int | float | None = None
    memory: int | float | None = None


@dataclass
class ManagedAgentSessionConfig:
    """Declarative configuration for a :class:`ManagedAgentSession`.

    Mirrors SkyPilot's task YAML schema:

    * ``resources``  ↔ ``sky.Resources``
    * ``envs``       ↔ task ``envs``
    * ``num_agents`` ↔ ``num_nodes``

    Load from YAML::

        cfg = ManagedAgentSessionConfig.from_yaml("session.yaml")
    """

    sweep_id: str
    entity: str
    project: str
    artifact_id: str
    num_agents: int = 1
    container_image: str = "python:3.11-slim"
    resources: SandboxResources | None = None
    envs: dict[str, str] = field(default_factory=dict)
    runway_ids: list[str] | None = None
    tower_ids: list[str] | None = None

    @classmethod
    def from_yaml(cls, path: str) -> ManagedAgentSessionConfig:
        """Load config from a YAML file."""
        with open(path) as fh:
            raw = yaml.safe_load(fh)
        resources_raw = raw.pop("resources", None)
        resources = SandboxResources(**resources_raw) if resources_raw else None
        return cls(**raw, resources=resources)

    def to_yaml(self, path: str) -> None:
        """Serialise config to a YAML file."""
        data: dict[str, Any] = {
            "sweep_id": self.sweep_id,
            "entity": self.entity,
            "project": self.project,
            "artifact_id": self.artifact_id,
            "num_agents": self.num_agents,
            "container_image": self.container_image,
        }
        if self.resources is not None:
            res: dict[str, Any] = {}
            if self.resources.accelerators is not None:
                res["accelerators"] = self.resources.accelerators
            if self.resources.cpus is not None:
                res["cpus"] = self.resources.cpus
            if self.resources.memory is not None:
                res["memory"] = self.resources.memory
            data["resources"] = res
        if self.envs:
            data["envs"] = self.envs
        if self.runway_ids:
            data["runway_ids"] = self.runway_ids
        if self.tower_ids:
            data["tower_ids"] = self.tower_ids
        with open(path, "w") as fh:
            yaml.safe_dump(data, fh, default_flow_style=False)


# ──────────────────────────────────────────────────────────────────────────────
# ManagedAgent — single-sandbox decorator
# ──────────────────────────────────────────────────────────────────────────────


class ManagedAgent:
    """Configures an Aviato sandbox to download artifact code and run a sweep agent.

    Typical usage — bring your own sandbox::

        from sandbox import AviatoSandbox
        from wandb.wandb_managed_agent import ManagedAgent

        managed = ManagedAgent(
            sweep_id="abc123",
            entity="acme",
            project="mnist",
            artifact_id="acme/mnist/training-code:latest",
        )

        sandbox = AviatoSandbox(
            command="sleep",
            args=["infinity"],
            container_image="python:3.11-slim",
        )
        managed.consume_sandbox(sandbox)   # tags the sandbox in-place
        sandbox.start()                    # caller owns lifecycle
        result = managed.run(sandbox).result()
        sandbox.stop()
    """

    def __init__(
        self,
        sweep_id: str,
        entity: str,
        project: str,
        artifact_id: str,
    ) -> None:
        self.sweep_id = sweep_id
        self.entity = entity
        self.project = project
        self.artifact_id = artifact_id
        self._api = InternalApi()

    @property
    def sweep_tag(self) -> str:
        """Sandbox tag used to identify sandboxes belonging to this sweep."""
        return f"wandb-sweep:{self.sweep_id}"

    def consume_sandbox(self, sandbox: AviatoSandbox) -> AviatoSandbox:
        """Tag *sandbox* in-place so it is identifiable as part of this sweep.

        Must be called **before** ``sandbox.start()``.  The caller is
        responsible for starting and stopping the sandbox.  After starting,
        call :meth:`run` to exec the agent startup script inside it.

        Args:
            sandbox: An unstarted :class:`~sandbox.AviatoSandbox`.

        Returns:
            The same *sandbox* instance (for chaining).
        """
        self._apply_tag(sandbox)
        return sandbox

    def run(
        self,
        sandbox: AviatoSandbox,
        *,
        timeout_seconds: int = _DEFAULT_EXEC_TIMEOUT_SECONDS,
    ) -> SandboxFuture[ExecResult]:
        """Execute the sweep agent startup script inside a running sandbox.

        Non-blocking — returns a :class:`~sandbox.future.SandboxFuture`
        immediately.  The sandbox must be running (``sleep infinity`` or any
        other keep-alive command) so that ``exec()`` can be issued against it.

        Args:
            sandbox: A running :class:`~sandbox.AviatoSandbox`.
            timeout_seconds: Maximum seconds for the exec.  Defaults to one
                week, which is long enough for any realistic sweep.

        Returns:
            A future that resolves to :class:`~sandbox.protocol.ExecResult`
            when ``wandb agent`` exits.
        """
        startup = self._build_startup_script()
        return sandbox.exec(["/bin/sh", "-c", startup], timeout_seconds=timeout_seconds)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_tag(self, sandbox: AviatoSandbox) -> None:
        tag = self.sweep_tag
        if sandbox._tags is None:
            sandbox._tags = [tag]
        elif tag not in sandbox._tags:
            sandbox._tags = list(sandbox._tags) + [tag]

    def _build_startup_script(self) -> str:
        """Return the shell one-liner run inside the sandbox."""
        sweep_path = f"{self.entity}/{self.project}/{self.sweep_id}"
        env_block = self._build_env_exports(sweep_path)
        extra_envs = " && ".join(
            f'export {k}="{v}"' for k, v in (self._extra_envs() or {}).items()
        )
        if extra_envs:
            env_block = f"{env_block} && {extra_envs}"
        return (
            f"{env_block} && "
            f"pip install --quiet wandb && "
            f"wandb artifact get {self.artifact_id} -d {_ARTIFACT_SANDBOX_ROOT} && "
            f"cd {_ARTIFACT_SANDBOX_ROOT} && "
            f"wandb agent {sweep_path}"
        )

    def _build_env_exports(self, sweep_path: str) -> str:
        """Build a single ``export K=V K=V …`` statement for core W&B vars."""
        pairs: list[str] = [
            f'WANDB_PROJECT="{self.project}"',
            f'WANDB_ENTITY="{self.entity}"',
            # Full path lets artifact code call
            # wandb.agent(os.environ["WANDB_SWEEP_ID"], function=train)
            f'WANDB_SWEEP_ID="{sweep_path}"',
        ]
        api_key = self._api.api_key
        if api_key:
            pairs.append(f'WANDB_API_KEY="{api_key}"')
        base_url = self._api.settings("base_url")
        if base_url:
            pairs.append(f'WANDB_BASE_URL="{base_url}"')
        return "export " + " ".join(pairs)

    def _extra_envs(self) -> dict[str, str]:
        """Subclasses or session config may inject additional env vars here."""
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# ManagedAgentSession — select-style pool monitoring
# ──────────────────────────────────────────────────────────────────────────────


class _SlotInfo(NamedTuple):
    """All state associated with one active sandbox slot."""

    index: int
    sandbox: AviatoSandbox


class ManagedAgentSession:
    """Manages a pool of sandboxes running ``wandb agent`` for a sweep.

    On :meth:`run`:

    1. Spawns ``config.num_agents`` Aviato sandboxes with ``sleep infinity``
       as the main command.
    2. Execs the artifact-download + ``wandb agent`` startup script inside
       each via :meth:`ManagedAgent.run`.
    3. Monitors all exec futures with ``concurrent.futures.wait()``
       (Python's ``select(2)`` for futures) — no per-sandbox monitor thread.
    4. Prints accumulated stdout per sandbox on completion, docker-compose
       style.
    5. Any sandbox whose agent exits non-zero is transparently replaced.
    """

    def __init__(self, config: ManagedAgentSessionConfig) -> None:
        self.config = config
        self._env: Environment | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> ManagedAgentSession:
        from sandbox import Environment

        self._env = Environment()
        return self

    def close(self) -> None:
        if self._env is not None:
            self._env.close().result()
            self._env = None

    def __enter__(self) -> ManagedAgentSession:
        return self.open()

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Launch agents and block until all have completed successfully."""
        if self._env is None:
            raise RuntimeError(
                "Session not open. Use 'with ManagedAgentSession(cfg) as s:' "
                "or call s.open() first."
            )
        self._run_pool()

    # ------------------------------------------------------------------
    # Pool management
    # ------------------------------------------------------------------

    def _run_pool(self) -> None:
        """Launch sandboxes, exec agents, and monitor with concurrent.futures.wait()."""
        # future → _SlotInfo  (select() fd table)
        active: dict[concurrent.futures.Future[Any], _SlotInfo] = {}

        for i in range(self.config.num_agents):
            sandbox, exec_future = self._make_sandbox_and_run(i)
            active[exec_future._future] = _SlotInfo(index=i, sandbox=sandbox)

        label_width = len(f"agent-{max(self.config.num_agents - 1, 0)}")

        while active:
            done, _ = concurrent.futures.wait(
                active.keys(),
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for fut in done:
                slot = active.pop(fut)
                exc = fut.exception()

                if exc is None:
                    result = fut.result()
                    self._print_output(slot.index, label_width, result)
                    rc = result.returncode
                else:
                    wandb.termlog(f"agent-{slot.index}: exec error — {exc!r}")
                    rc = 1

                slot.sandbox.stop()

                if rc == 0:
                    wandb.termlog(f"agent-{slot.index}: completed")
                    continue

                wandb.termlog(f"agent-{slot.index}: exit {rc} — restarting")
                new_sandbox, new_future = self._make_sandbox_and_run(slot.index)
                active[new_future._future] = _SlotInfo(index=slot.index, sandbox=new_sandbox)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_sandbox_and_run(
        self, index: int
    ) -> tuple[AviatoSandbox, SandboxFuture[ExecResult]]:
        """Create, configure, and start a sandbox, then exec the agent."""
        from sandbox import AviatoSandbox

        managed = ManagedAgent(
            sweep_id=self.config.sweep_id,
            entity=self.config.entity,
            project=self.config.project,
            artifact_id=self.config.artifact_id,
        )
        if self.config.envs:
            managed.__class__ = _ManagedAgentWithExtraEnvs
            managed._extra_env_dict = self.config.envs  # type: ignore[attr-defined]

        extra: dict[str, Any] = {}
        if self.config.runway_ids:
            extra["runway_ids"] = self.config.runway_ids
        if self.config.tower_ids:
            extra["tower_ids"] = self.config.tower_ids

        sandbox = AviatoSandbox(
            command="sleep",
            args=["infinity"],
            container_image=self.config.container_image,
            environment=self._env,
            **extra,
        )
        managed.consume_sandbox(sandbox)  # tags the sandbox before start
        sandbox.start()
        exec_future = managed.run(sandbox)
        return sandbox, exec_future

    @staticmethod
    def _print_output(index: int, label_width: int, result: ExecResult) -> None:
        """Print accumulated stdout from a completed exec, docker-compose style."""
        colour = _LABEL_COLOURS[index % len(_LABEL_COLOURS)]
        label = f"agent-{index}"
        for line in result.stdout.decode(errors="replace").splitlines():
            sys.stdout.write(f"{colour}{label:<{label_width}}{_RESET}  | {line}\n")
        sys.stdout.flush()


class _ManagedAgentWithExtraEnvs(ManagedAgent):
    """Internal subclass that injects session-level envs into the startup script."""

    _extra_env_dict: dict[str, str]

    def _extra_envs(self) -> dict[str, str]:
        return self._extra_env_dict


