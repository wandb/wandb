"""Managed sweep agents that run inside W&B sandboxes.

``ManagedAgent`` configures a single sandbox in-place so that starting it
automatically downloads the artifact code and runs ``wandb agent``.

``ManagedAgentSession`` manages a pool of such sandboxes.  Sandbox lifecycle
is monitored with ``concurrent.futures.wait()`` — the Python equivalent of
``select(2)`` for futures — so there is **no per-sandbox monitor thread**.
Log lines are read in thread-pool threads (one per active sandbox) and funnel
through a single shared ``queue.Queue`` to a dedicated printer thread that
serialises writes, docker-compose style:

    agent-0  | Starting sweep agent…
    agent-1  | Starting sweep agent…
    agent-0  | Run abc123 — lr=0.001

Thread budget for N parallel agents: N log-stream threads + 1 printer thread.
The main thread spends its time in ``concurrent.futures.wait()``.

The session configuration is modelled after SkyPilot's task-YAML schema.

Quick start::

    import wandb
    from wandb.wandb_managed_agent import (
        ManagedAgentSession,
        ManagedAgentSessionConfig,
        EnvOnlySource,
        CodeArtifactSource,
        JobArtifactSource,
    )

    # Case 1 — image already has code + wandb installed
    cfg = ManagedAgentSessionConfig(
        sweep_id="abc123", entity="acme", project="mnist",
        source=EnvOnlySource(),
        container_image="my-registry/training:latest",
    )

    # Case 2 — generic image; code downloaded via artifact
    cfg = ManagedAgentSessionConfig(
        sweep_id="abc123", entity="acme", project="mnist",
        source=CodeArtifactSource("acme/mnist/training-code:latest"),
    )

    # Case 3 — W&B job artifact whose wandb-job.json specifies a docker image
    cfg = ManagedAgentSessionConfig(
        sweep_id="abc123", entity="acme", project="mnist",
        source=JobArtifactSource("acme/mnist/my-job:latest"),
    )

    with ManagedAgentSession(cfg) as session:
        session.run()

YAML example (``sweep_session.yaml``)::

    sweep_id: abc123
    entity: acme
    project: mnist
    artifact_id: acme/mnist/training-code:latest   # sets CodeArtifactSource
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
import enum
import logging
import queue
import sys
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable, Iterator, NamedTuple, Protocol, runtime_checkable

import yaml

import wandb
from wandb.apis import InternalApi

from cwsandbox import NetworkOptions

if TYPE_CHECKING:
    from wandb.sandbox._sandbox import Sandbox
    from wandb.sandbox._session import Session

logger = logging.getLogger(__name__)

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

# Sentinel that tells the printer thread to exit.
_PRINTER_STOP = object()


# ──────────────────────────────────────────────────────────────────────────────
# Restart policy flags
# ──────────────────────────────────────────────────────────────────────────────


class RestartPolicy(enum.IntFlag):
    """Bitmask controlling which sandbox exit conditions trigger a restart.

    Combine flags with ``|``::

        from wandb.wandb_managed_agent import RestartPolicy

        auto_restart = RestartPolicy.ON_FAILED | RestartPolicy.ON_TERMINATED

    Flags:

    * ``ON_FAILED``     — agent process exited with a non-zero return code.
    * ``ON_TERMINATED`` — sandbox was stopped externally (TERMINATED status).
    * ``ON_TIMEOUT``    — sandbox exceeded its configured max lifetime.
    """

    ON_FAILED = enum.auto()
    ON_TERMINATED = enum.auto()
    ON_TIMEOUT = enum.auto()


# ──────────────────────────────────────────────────────────────────────────────
# RunHandle — public return type of AgentSource.start()
# ──────────────────────────────────────────────────────────────────────────────


class RunHandle:
    """Returned by :meth:`AgentSource.start`.

    Provides a select-able future and an optional log-line stream.  The
    session owns all queue and thread infrastructure; the source only
    provides raw material.

    Attributes:
        future: ``concurrent.futures.Future`` that resolves when the agent
            (or bootstrap thread) completes.
        log_lines: Iterable of log line strings, or ``None`` if the source
            does not support streaming (e.g. log streaming is disabled).
    """

    def __init__(
        self,
        future: concurrent.futures.Future,
        log_lines: Iterable[str] | None = None,
        _closer: Callable[[], None] | None = None,
    ) -> None:
        self.future = future
        self.log_lines = log_lines
        self._closer = _closer

    def close(self) -> None:
        """Stop the log stream.  No-op if there is no closer."""
        if self._closer is not None:
            self._closer()


# ──────────────────────────────────────────────────────────────────────────────
# _SlotInfo — active sandbox state (internal)
# ──────────────────────────────────────────────────────────────────────────────


class _SlotInfo(NamedTuple):
    """All state associated with one active sandbox slot."""

    index: int
    sandbox: Sandbox
    handle: RunHandle
    log_thread: threading.Thread | None


# ──────────────────────────────────────────────────────────────────────────────
# AgentSource — Strategy protocol
# ──────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class AgentSource(Protocol):
    """Strategy interface that encapsulates the three sandbox source modes.

    Concrete implementations:

    * :class:`EnvOnlySource`      — Case 1: image already has code + wandb.
    * :class:`CodeArtifactSource` — Case 2: generic image; exec bootstrap.
    * :class:`JobArtifactSource`  — Case 3: job artifact specifies docker image.
    """

    def get_image(self, default: str) -> str:
        """Return the container image to use.

        May download metadata on the host (Case 3); other sources return
        *default* unchanged.
        """
        ...

    def apply_command(self, sandbox: Sandbox, sweep_path: str) -> None:
        """Set the sandbox's startup command before ``sandbox.start()``.

        * Cases 1 & 3: ``wandb agent <sweep_path>``
        * Case 2: ``sleep infinity`` (agent started later via exec)
        """
        ...

    def start(self, sandbox: Sandbox, sweep_path: str) -> RunHandle:
        """Post-start attachment: return a :class:`RunHandle` for this sandbox.

        Called after ``sandbox.start().result()``.  Returns a
        :class:`RunHandle` whose ``future`` resolves when the agent (or
        bootstrap thread) finishes, and whose ``log_lines`` is an iterable
        of log-line strings (or ``None`` if not applicable).

        The caller owns all queue and thread infrastructure; the source only
        provides the raw future and log stream.
        """
        ...


# ──────────────────────────────────────────────────────────────────────────────
# Concrete AgentSource implementations
# ──────────────────────────────────────────────────────────────────────────────


class EnvOnlySource:
    """Case 1: the container image already contains the code and ``wandb``.

    The sandbox starts with ``wandb agent`` as its main command; no exec-based
    bootstrap is required.
    """

    def get_image(self, default: str) -> str:
        return default

    def apply_command(self, sandbox: Sandbox, sweep_path: str) -> None:
        print(f"[DEBUG] EnvOnlySource.apply_command: wandb agent {sweep_path}")
        sandbox._command = "wandb"
        sandbox._args = ["agent", sweep_path]

    def start(self, sandbox: Sandbox, sweep_path: str) -> RunHandle:
        reader = sandbox.stream_logs(follow=True)
        future = sandbox.wait_until_complete(raise_on_termination=True)._future
        return RunHandle(future=future, log_lines=reader, _closer=reader.close)


class CodeArtifactSource:
    """Case 2: generic image; job artifact code source exec-bootstrapped after start.

    The sandbox starts with ``sleep infinity`` as its main command.  After
    ``sandbox.start()``, :meth:`start` submits a bootstrap thread that mirrors
    ``wandb.superagent.main._sandbox_bootstrap``:

    1. ``pip install wandb``
    2. Write ``wandb.superagent.scripts.download_job_artifact`` into sandbox and exec
       it to download the job artifact to ``/job``.
    3. Write ``wandb.superagent.bootstrap`` into sandbox and exec it to materialise
       the source code into ``/workspace``.
    4. ``pip install -r /workspace/requirements.frozen.txt`` (if present)
    5. ``wandb agent <sweep_path>`` (blocks until the agent exits)

    The bootstrap thread future is returned as the select-able future so the
    pool can detect completion or failure.

    Args:
        job_artifact_id: Fully-qualified W&B **job** artifact path, e.g.
            ``entity/project/my-job:latest``.  The job's ``wandb-job.json``
            must have ``source_type`` of ``artifact`` or ``repo``.
    """

    def __init__(self, job_artifact_id: str) -> None:
        self.job_artifact_id = job_artifact_id

    def get_image(self, default: str) -> str:
        return default

    def apply_command(self, sandbox: Sandbox, sweep_path: str) -> None:
        print("[DEBUG] CodeArtifactSource.apply_command: sleep infinity (exec bootstrap)")
        sandbox._command = "sleep"
        sandbox._args = ["infinity"]

    def start(self, sandbox: Sandbox, sweep_path: str) -> RunHandle:
        _line_queue: queue.SimpleQueue[str | None] = queue.SimpleQueue()

        def on_log(line: str) -> None:
            _line_queue.put(line)

        def bootstrap() -> None:
            try:
                _bootstrap_artifact_agent(sandbox, self.job_artifact_id, sweep_path, on_log)
            finally:
                _line_queue.put(None)  # sentinel — drain thread exits cleanly

        def _log_gen() -> Iterator[str]:
            while True:
                line = _line_queue.get()
                if line is None:
                    return
                yield line

        future = _bootstrap_executor.submit(bootstrap)
        return RunHandle(future=future, log_lines=_log_gen())


class JobArtifactSource:
    """Case 3: W&B job artifact whose ``wandb-job.json`` specifies a docker image.

    :meth:`get_image` downloads the job artifact on the host, reads
    ``wandb-job.json``, and returns ``source.image``.  The sandbox then starts
    with ``wandb agent`` as its main command (same as Case 1).
    """

    def __init__(self, job_artifact_id: str) -> None:
        self.job_artifact_id = job_artifact_id

    def get_image(self, default: str) -> str:
        import json
        import os
        import tempfile

        from wandb.apis.public import Api

        print(f"[DEBUG] JobArtifactSource.get_image: fetching job artifact '{self.job_artifact_id}'")
        api = Api()
        artifact = api._artifact(self.job_artifact_id, type="job")
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact.download(root=tmp_dir)
            job_json_path = os.path.join(tmp_dir, "wandb-job.json")
            with open(job_json_path, encoding="utf-8") as f:
                spec = json.load(f)
        if spec.get("source_type") == "image":
            image = (spec.get("source") or {}).get("image", "").strip()
            if image:
                print(f"[DEBUG] JobArtifactSource.get_image: image='{image}'")
                return image
        print(f"[DEBUG] JobArtifactSource.get_image: source_type={spec.get('source_type')!r}, falling back to default '{default}'")
        return default

    def apply_command(self, sandbox: Sandbox, sweep_path: str) -> None:
        print(f"[DEBUG] JobArtifactSource.apply_command: wandb agent {sweep_path}")
        sandbox._command = "wandb"
        sandbox._args = ["agent", sweep_path]

    def start(self, sandbox: Sandbox, sweep_path: str) -> RunHandle:
        reader = sandbox.stream_logs(follow=True)
        future = sandbox.wait_until_complete(raise_on_termination=True)._future
        return RunHandle(future=future, log_lines=reader, _closer=reader.close)


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

    ``cpus`` and ``memory`` (GiB) map to the cwsandbox ``resources`` dict.
    """

    accelerators: str | dict[str, int] | None = None
    cpus: int | float | None = None
    memory: int | float | None = None

    def to_cwsandbox_dict(self) -> dict[str, Any] | None:
        """Convert to the ``resources`` dict expected by cwsandbox.

        cwsandbox expects::

            {
                "cpu": "2",
                "memory": "8Gi",
                "gpu": {"gpu_count": 1},   # nested GpuRequest
            }
        """
        result: dict[str, Any] = {}
        if self.accelerators is not None:
            if isinstance(self.accelerators, str):
                if ":" in self.accelerators:
                    _, count = self.accelerators.rsplit(":", 1)
                    result["gpu"] = {"gpu_count": int(count)}
                else:
                    result["gpu"] = {"gpu_count": 1}
            else:
                result["gpu"] = {"gpu_count": sum(self.accelerators.values())}
        if self.cpus is not None:
            result["cpu"] = str(self.cpus)
        if self.memory is not None:
            result["memory"] = f"{self.memory}Gi"
        return result or None


@dataclass
class ManagedAgentSessionConfig:
    """Declarative configuration for a :class:`ManagedAgentSession`.

    Mirrors SkyPilot's task YAML schema:

    * ``resources``  ↔ ``sky.Resources``
    * ``envs``       ↔ task ``envs``
    * ``num_agents`` ↔ ``num_nodes``

    The ``source`` field is an :class:`AgentSource` that encapsulates which of
    the three sandbox source modes to use:

    * :class:`EnvOnlySource`      — image already has code + wandb (default).
    * :class:`CodeArtifactSource` — generic image; exec bootstrap via artifact.
    * :class:`JobArtifactSource`  — job artifact whose spec specifies an image.

    Load from YAML::

        cfg = ManagedAgentSessionConfig.from_yaml("session.yaml")

    YAML keys ``artifact_id`` and ``job_artifact_id`` are auto-converted to
    :class:`CodeArtifactSource` and :class:`JobArtifactSource` respectively.
    """

    sweep_id: str
    entity: str
    project: str
    source: AgentSource = field(default_factory=EnvOnlySource)
    num_agents: int = 1
    container_image: str = "python:3.11-slim"
    resources: SandboxResources | None = None
    envs: dict[str, str] = field(default_factory=dict)
    runway_ids: list[str] | None = None
    tower_ids: list[str] | None = None
    auto_restart: int = 0  # OR of RestartPolicy flags; 0 means no restart

    @classmethod
    def from_yaml(cls, path: str) -> ManagedAgentSessionConfig:
        """Load config from a YAML file.

        YAML keys ``artifact_id`` and ``job_artifact_id`` are converted to
        :class:`CodeArtifactSource` and :class:`JobArtifactSource`.
        """
        with open(path) as fh:
            raw = yaml.safe_load(fh)
        resources_raw = raw.pop("resources", None)
        resources = SandboxResources(**resources_raw) if resources_raw else None
        artifact_id = raw.pop("artifact_id", None)
        job_artifact_id = raw.pop("job_artifact_id", None)
        sweep_id = raw.pop("sweep_id", "")
        entity = raw.pop("entity", "")
        project = raw.pop("project", "")
        if artifact_id:
            source: AgentSource = CodeArtifactSource(artifact_id)
        elif job_artifact_id:
            source = JobArtifactSource(job_artifact_id)
        else:
            source = EnvOnlySource()
        return cls(
            sweep_id=sweep_id,
            entity=entity,
            project=project,
            **raw,
            resources=resources,
            source=source,
        )

    def to_yaml(self, path: str) -> None:
        """Serialise config to a YAML file."""
        data: dict[str, Any] = {
            "sweep_id": self.sweep_id,
            "entity": self.entity,
            "project": self.project,
            "num_agents": self.num_agents,
            "container_image": self.container_image,
        }
        if isinstance(self.source, CodeArtifactSource):
            data["artifact_id"] = self.source.artifact_id
        elif isinstance(self.source, JobArtifactSource):
            data["job_artifact_id"] = self.source.job_artifact_id
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
    """Configures a W&B sandbox to run a sweep agent.

    Delegates source-specific behavior to the injected :class:`AgentSource`
    strategy, keeping this class free of ``if artifact_id`` / ``if job_artifact_id``
    branches.

    Typical usage::

        source = CodeArtifactSource("acme/mnist/training-code:latest")
        managed = ManagedAgent(sweep_id="abc123", entity="acme", project="mnist",
                               source=source)
        with Session() as session:
            image = managed.resolve_container_image(default="python:3.11-slim")
            sandbox = session.sandbox(container_image=image)
            managed.consume_sandbox(sandbox)
            sandbox.start().result()
            handle = source.start(sandbox, managed._sweep_path)
            handle.future.result()
    """

    def __init__(
        self,
        sweep_id: str,
        entity: str,
        project: str,
        source: AgentSource,
    ) -> None:
        self.sweep_id = sweep_id
        self.entity = entity
        self.project = project
        self.source = source
        self._api = InternalApi()

    @property
    def sweep_tag(self) -> str:
        """Sandbox tag used to identify sandboxes belonging to this sweep."""
        return f"wandb-sweep-{self.sweep_id}"

    @property
    def _sweep_path(self) -> str:
        return f"{self.entity}/{self.project}/{self.sweep_id}"

    def resolve_container_image(self, default: str = "python:3.11-slim") -> str:
        """Return the container image to use, delegating to the source strategy."""
        return self.source.get_image(default)

    def consume_sandbox(self, sandbox: Sandbox) -> Sandbox:
        """Configure *sandbox* before ``sandbox.start()``.

        Sets the sweep tag, W&B env vars, and delegates the startup command to
        the :class:`AgentSource` strategy.

        Returns:
            The same *sandbox* instance (for chaining).
        """
        print(f"[DEBUG] consume_sandbox: configuring sandbox for sweep '{self.sweep_id}' source={type(self.source).__name__}")
        self._apply_tag(sandbox)
        self._apply_env_vars(sandbox)
        self._apply_network(sandbox)
        self.source.apply_command(sandbox, self._sweep_path)
        print(f"[DEBUG] consume_sandbox: done — command={sandbox._command!r} args={sandbox._args!r}")
        return sandbox

    def log_device_resources(
        self,
        sandbox: Sandbox,
        log_queue: queue.Queue | None = None,
        label: str = "agent",
    ) -> None:
        """Exec resource-inspection commands in *sandbox* and log the results.

        Runs three commands — CPU count, memory, and GPU info — immediately
        after ``sandbox.start()`` so the output appears before any agent work
        begins.  Failures (e.g. no ``nvidia-smi``) are logged as warnings
        rather than raised.

        Args:
            sandbox: A running sandbox to inspect.
            log_queue: If provided, lines are pushed as ``(label, line)``
                tuples (docker-compose style).  Otherwise printed to stdout.
            label: Log prefix, e.g. ``"agent-0"``.
        """
        def _emit(line: str) -> None:
            if log_queue is not None:
                log_queue.put((label, line))
            else:
                print(f"{label}  | {line}")

        commands: list[tuple[list[str], str]] = [
            (
                ["sh", "-c", "awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo"],
                "CPU model",
            ),
            (["nproc"], "CPU"),
            (
                ["sh", "-c", "awk '/MemTotal/{printf \"%.1f GiB\\n\", $2/1048576}' /proc/meminfo"],
                "Memory",
            ),
            (
                ["sh", "-c", "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'no GPU'"],
                "GPU",
            ),
        ]
        _emit("[wandb] --- device resources ---")
        for cmd, resource_name in commands:
            try:
                proc = sandbox.exec(cmd)
                lines: list[str] = []

                def _drain_reader(reader, _lines: list = lines) -> None:
                    for line in reader:
                        _lines.append(line.rstrip())

                t_out = threading.Thread(target=_drain_reader, args=(proc.stdout,), daemon=True)
                t_err = threading.Thread(target=_drain_reader, args=(proc.stderr,), daemon=True)
                t_out.start()
                t_err.start()
                t_out.join()
                t_err.join()
                result = proc.result()
                if result.returncode != 0:
                    _emit(f"[wandb] {resource_name}: (exit {result.returncode})")
                else:
                    for line in lines:
                        _emit(f"[wandb] {resource_name}: {line}")
            except Exception as exc:
                _emit(f"[wandb] {resource_name}: WARNING — {exc}")
        _emit("[wandb] --- end device resources ---")

    def _apply_network(self, sandbox: Sandbox) -> None:
        network = NetworkOptions(egress_mode="internet")
        print(f"[DEBUG] _apply_network: egress_mode='internet'")
        sandbox._start_kwargs["network"] = network

    def _apply_tag(self, sandbox: Sandbox) -> None:
        tag = self.sweep_tag
        print(f"[DEBUG] _apply_tag: adding tag '{tag}'")
        if sandbox._tags is None:
            sandbox._tags = [tag]
        elif tag not in sandbox._tags:
            sandbox._tags = list(sandbox._tags) + [tag]

    def _apply_env_vars(self, sandbox: Sandbox) -> None:
        updates: dict[str, str] = {
            "WANDB_PROJECT": self.project,
            "WANDB_ENTITY": self.entity,
            "WANDB_SWEEP_ID": self._sweep_path,
        }
        api_key = self._api.api_key
        if api_key:
            sandbox_updates = {**updates, "WANDB_API_KEY": api_key}
            print(f"[DEBUG] _apply_env_vars: setting {updates} + WANDB_API_KEY=<redacted>")
        else:
            sandbox_updates = dict(updates)
            print("[DEBUG] _apply_env_vars: WARNING — no WANDB_API_KEY found")
        base_url = self._api.settings("base_url")
        if base_url:
            sandbox_updates["WANDB_BASE_URL"] = base_url
            print(f"[DEBUG] _apply_env_vars: WANDB_BASE_URL={base_url!r}")
        existing = dict(sandbox._environment_variables or {})
        existing.update(sandbox_updates)
        sandbox._environment_variables = existing


# ──────────────────────────────────────────────────────────────────────────────
# ManagedAgentSession — thread-based pool with select-style monitoring
# ──────────────────────────────────────────────────────────────────────────────


class ManagedAgentSession:
    """Manages a pool of sandboxes running ``wandb agent`` for a sweep.

    On :meth:`run`:

    1. Adopts any sandboxes already tagged ``wandb-sweep-<sweep_id>``
       so the pool survives process restarts.
    2. Spawns new sandboxes up to ``config.num_agents``.
    3. Monitors all completion futures with ``concurrent.futures.wait()``
       (Python's ``select(2)`` for futures) — no per-sandbox monitor thread.
    4. When ``attach_logs=True`` is passed to :meth:`run`, log lines flow
       through a single ``queue.Queue`` to a dedicated printer thread
       (docker-compose style).
    5. Any sandbox that exits non-zero or raises is transparently replaced.
    """

    def __init__(self, config: ManagedAgentSessionConfig) -> None:
        self.config = config
        self._session: Session | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> ManagedAgentSession:
        print("[DEBUG] ManagedAgentSession.open: creating W&B sandbox session")
        from wandb.sandbox import Session

        self._session = Session().__enter__()
        print("[DEBUG] ManagedAgentSession.open: session ready")
        return self

    def close(self) -> None:
        print("[DEBUG] ManagedAgentSession.close: closing session")
        if self._session is not None:
            self._session.__exit__(None, None, None)
            self._session = None

    def __enter__(self) -> ManagedAgentSession:
        return self.open()

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, *, attach_logs: bool = False) -> None:
        """Adopt existing sandboxes, launch new agents, and block until done.

        Args:
            attach_logs: When ``True``, stream sandbox logs to stdout in
                docker-compose style (``agent-0  | log line``).
        """
        if self._session is None:
            raise RuntimeError(
                "Session not open. Use 'with ManagedAgentSession(cfg) as s:' "
                "or call s.open() first."
            )

        print(f"[DEBUG] run: starting pool for sweep '{self.config.sweep_id}' with {self.config.num_agents} agent(s) attach_logs={attach_logs}")
        log_queue: queue.Queue[tuple[str, str] | object] | None = None
        printer: threading.Thread | None = None

        if attach_logs:
            label_width = len(f"agent-{max(self.config.num_agents - 1, 0)}")
            log_queue = queue.Queue()
            printer = threading.Thread(
                target=_printer_thread,
                args=(log_queue, label_width),
                name="wandb-log-printer",
                daemon=True,
            )
            printer.start()
            print("[DEBUG] run: printer thread started")

        try:
            self._run_pool(log_queue)
        finally:
            if log_queue is not None and printer is not None:
                log_queue.put(_PRINTER_STOP)
                printer.join()
                print("[DEBUG] run: printer thread joined — done")

    # ------------------------------------------------------------------
    # Pool management
    # ------------------------------------------------------------------

    def _run_pool(self, log_queue: queue.Queue | None) -> None:
        """Launch sandboxes and monitor them with concurrent.futures.wait()."""
        sweep_tag = f"wandb-sweep-{self.config.sweep_id}"
        print(f"[DEBUG] _run_pool: sweep_tag='{sweep_tag}'")

        # Adopt any sandboxes already running for this sweep.
        print("[DEBUG] _run_pool: listing existing sandboxes to adopt ...")
        existing: list[Sandbox] = self._session.list(  # type: ignore[union-attr]
            tags=[sweep_tag], adopt=True
        ).result()
        print(f"[DEBUG] _run_pool: found {len(existing)} existing sandbox(es)")
        if existing:
            wandb.termlog(
                f"Adopted {len(existing)} existing sandbox(es) for "
                f"sweep '{self.config.sweep_id}'."
            )

        # future → _SlotInfo  (select() fd table)
        active: dict[concurrent.futures.Future, _SlotInfo] = {}

        # Adopted sandboxes are always Cases 1/3 (exec bootstrap can't be adopted).
        for i, sandbox in enumerate(existing):
            print(f"[DEBUG] _run_pool: attaching adopted sandbox {i} id={sandbox.sandbox_id}")
            reader = sandbox.stream_logs(follow=True)
            handle = RunHandle(
                future=sandbox.wait_until_complete(raise_on_termination=True)._future,
                log_lines=reader,
                _closer=reader.close,
            )
            log_thread = _start_log_drain(handle, f"agent-{i}", log_queue)
            active[handle.future] = _SlotInfo(index=i, sandbox=sandbox, handle=handle, log_thread=log_thread)

        new_count = max(0, self.config.num_agents - len(existing))
        print(f"[DEBUG] _run_pool: launching {new_count} new sandbox(es)")
        for i in range(len(existing), len(existing) + new_count):
            print(f"[DEBUG] _run_pool: creating sandbox {i} ...")
            future, slot = self._make_and_start_sandbox(i, log_queue)
            print(f"[DEBUG] _run_pool: sandbox {i} started — id={slot.sandbox.sandbox_id}")
            active[future] = slot

        print(f"[DEBUG] _run_pool: entering wait loop with {len(active)} active sandbox(es)")
        while active:
            print(f"[DEBUG] _run_pool: calling concurrent.futures.wait on {len(active)} future(s) ...")
            done, _ = concurrent.futures.wait(
                active.keys(),
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            print(f"[DEBUG] _run_pool: wait returned — {len(done)} future(s) done")

            for future in done:
                slot = active.pop(future)
                print(f"[DEBUG] _run_pool: agent-{slot.index} future completed")
                slot.handle.close()
                if slot.log_thread is not None:
                    slot.log_thread.join(timeout=10)

                exc = future.exception()
                print(f"[DEBUG] _run_pool: agent-{slot.index} exc={exc!r}")

                if exc is None:
                    if log_queue is not None:
                        log_queue.put((f"agent-{slot.index}", "[wandb] completed"))
                    continue

                if _should_restart(exc, self.config.auto_restart):
                    if log_queue is not None:
                        log_queue.put(
                            (f"agent-{slot.index}", f"[wandb] {exc!r} — restarting")
                        )
                    print(f"[DEBUG] _run_pool: restarting agent-{slot.index}")
                    new_future, new_slot = self._make_and_start_sandbox(slot.index, log_queue)
                    active[new_future] = new_slot
                else:
                    if log_queue is not None:
                        log_queue.put(
                            (f"agent-{slot.index}", f"[wandb] {exc!r} — exiting")
                        )

        print("[DEBUG] _run_pool: all sandboxes done")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_and_start_sandbox(
        self, index: int, log_queue: queue.Queue | None
    ) -> tuple[concurrent.futures.Future, _SlotInfo]:
        """Create, configure, start, and attach a sandbox slot.

        Delegates source-specific image resolution, command setup, and
        post-start attachment entirely to ``config.source``.
        """
        assert self._session is not None
        resources_dict = (
            self.config.resources.to_cwsandbox_dict()
            if self.config.resources
            else None
        )

        managed = ManagedAgent(
            sweep_id=self.config.sweep_id,
            entity=self.config.entity,
            project=self.config.project,
            source=self.config.source,
        )

        image = managed.resolve_container_image(self.config.container_image)
        print(f"[DEBUG] _make_and_start_sandbox: image={image!r} resources={resources_dict}")

        sandbox = self._session.sandbox(
            container_image=image,
            resources=resources_dict,
            runway_ids=self.config.runway_ids,
            tower_ids=self.config.tower_ids,
        )
        managed.consume_sandbox(sandbox)

        # Merge session-level envs on top of what ManagedAgent set.
        if self.config.envs:
            existing = dict(sandbox._environment_variables or {})
            existing.update(self.config.envs)
            sandbox._environment_variables = existing

        print("[DEBUG] _make_and_start_sandbox: calling sandbox.start() ...")
        sandbox.start().result()
        print(f"[DEBUG] _make_and_start_sandbox: sandbox running — id={sandbox.sandbox_id}")

        # [DEBUG] Log on-device resources immediately after start so we can
        # verify they match what was requested in resources.yaml.
        managed.log_device_resources(sandbox, log_queue, label=f"agent-{index}")

        handle = self.config.source.start(sandbox, managed._sweep_path)
        log_thread = _start_log_drain(handle, f"agent-{index}", log_queue)
        slot = _SlotInfo(index=index, sandbox=sandbox, handle=handle, log_thread=log_thread)
        return handle.future, slot


# ──────────────────────────────────────────────────────────────────────────────
# Thread helpers (free functions — easier to profile and test)
# ──────────────────────────────────────────────────────────────────────────────


_bootstrap_executor = concurrent.futures.ThreadPoolExecutor(
    thread_name_prefix="wandb-bootstrap"
)


_REMOTE_DOWNLOAD_SCRIPT = "/tmp/wandb_superagent_download_job.py"
_REMOTE_BOOTSTRAP_SCRIPT = "/tmp/wandb_superagent_bootstrap.py"
_REMOTE_WORKSPACE = "/workspace"
_REMOTE_JOB_DIR = "/job"


def _bootstrap_artifact_agent(
    sandbox: Sandbox,
    job_artifact_id: str,
    sweep_path: str,
    on_log: Callable[[str], None] | None = None,
) -> None:
    """Bootstrap a job artifact inside *sandbox* and run ``wandb agent``.

    Mirrors ``wandb.superagent.main._sandbox_bootstrap``: writes the
    superagent scripts into the sandbox and execs them rather than
    hand-rolling individual CLI commands.

    Must be called after ``sandbox.start().result()``.  Blocks until
    ``wandb agent`` exits.  Designed to run in a daemon thread via
    :data:`_bootstrap_executor`.

    Raises:
        cwsandbox.exceptions.SandboxFailedError: if any exec step exits
            with a non-zero return code.
    """
    from pathlib import Path

    from cwsandbox.exceptions import SandboxFailedError

    superagent_dir = Path(__file__).resolve().parent / "superagent"
    download_script_bytes = (superagent_dir / "scripts" / "download_job_artifact.py").read_bytes()
    bootstrap_script_bytes = (superagent_dir / "bootstrap.py").read_bytes()

    def _drain(reader) -> None:
        for line in reader:
            if on_log is not None:
                on_log(line.rstrip("\n"))

    def _exec_checked(cmd: list[str], *, step: str, cwd: str | None = None) -> None:
        print(f"[DEBUG] _bootstrap_artifact_agent: exec {step}: {cmd} cwd={cwd!r}")
        proc = sandbox.exec(cmd, cwd=cwd)
        t_out = threading.Thread(target=_drain, args=(proc.stdout,), daemon=True)
        t_err = threading.Thread(target=_drain, args=(proc.stderr,), daemon=True)
        t_out.start()
        t_err.start()
        t_out.join()
        t_err.join()
        result = proc.result()
        print(f"[DEBUG] _bootstrap_artifact_agent: {step} exit={result.returncode}")
        if result.returncode != 0:
            raise SandboxFailedError(
                f"Sandbox {sandbox.sandbox_id} bootstrap step '{step}' "
                f"exited {result.returncode}"
            )

    print(f"[DEBUG] _bootstrap_artifact_agent: starting bootstrap for job artifact '{job_artifact_id}'")

    # 1. Prepare directories
    sandbox.exec(["mkdir", "-p", _REMOTE_JOB_DIR]).result()
    sandbox.exec(["mkdir", "-p", _REMOTE_WORKSPACE]).result()

    # 2. Install wandb inside the sandbox
    _exec_checked(
        ["python", "-m", "pip", "install", "--no-cache-dir", "wandb"],
        step="pip install wandb",
    )

    # 3. Write and run download_job_artifact.py (from wandb.superagent.scripts)
    sandbox.write_file(_REMOTE_DOWNLOAD_SCRIPT, download_script_bytes).result()
    _exec_checked(
        ["python", _REMOTE_DOWNLOAD_SCRIPT, "--job-artifact", job_artifact_id, "--root", _REMOTE_JOB_DIR],
        step="download job artifact",
    )

    # 4. Write and run bootstrap.py (from wandb.superagent.bootstrap)
    sandbox.write_file(_REMOTE_BOOTSTRAP_SCRIPT, bootstrap_script_bytes).result()
    _exec_checked(
        ["python", _REMOTE_BOOTSTRAP_SCRIPT, "--workspace", _REMOTE_WORKSPACE],
        step="bootstrap",
    )

    # 5. Install workspace dependencies if present
    req_path = f"{_REMOTE_WORKSPACE}/requirements.frozen.txt"
    probe = sandbox.exec(["test", "-f", req_path]).result()
    if probe.returncode == 0:
        _exec_checked(
            ["python", "-m", "pip", "install", "--no-cache-dir", "-r", req_path],
            step="pip install requirements",
        )

    # 6. Run the sweep agent from the workspace so train.py is on the path
    _exec_checked(
        ["wandb", "agent", sweep_path],
        step="wandb agent",
        cwd=_REMOTE_WORKSPACE,
    )


def _should_restart(exc: BaseException | None, policy: int) -> bool:
    """Return True if *policy* says we should restart given this exit condition.

    With ``raise_on_termination=True``, ``exc is None`` means a clean exit
    (returncode 0).  Every other outcome surfaces as a typed exception:

    * ``SandboxFailedError``    → ``RestartPolicy.ON_FAILED``
    * ``SandboxTerminatedError`` → ``RestartPolicy.ON_TERMINATED``
    * ``SandboxTimeoutError``   → ``RestartPolicy.ON_TIMEOUT``
    """
    if exc is None:
        return False

    from cwsandbox.exceptions import (
        SandboxFailedError,
        SandboxTerminatedError,
        SandboxTimeoutError,
    )

    if isinstance(exc, SandboxTerminatedError):
        return bool(policy & RestartPolicy.ON_TERMINATED)
    if isinstance(exc, SandboxTimeoutError):
        return bool(policy & RestartPolicy.ON_TIMEOUT)
    if isinstance(exc, SandboxFailedError):
        return bool(policy & RestartPolicy.ON_FAILED)
    return False


def _start_log_drain(
    handle: RunHandle, label: str, log_queue: queue.Queue | None
) -> threading.Thread | None:
    """Spawn a drain thread for *handle.log_lines* if logging is enabled.

    Returns the thread (already started), or ``None`` if *log_queue* is
    ``None`` or *handle.log_lines* is ``None``.
    """
    if log_queue is None or handle.log_lines is None:
        return None
    thread = threading.Thread(
        target=_drain_iterable_to_queue,
        args=(handle.log_lines, label, log_queue),
        name=f"wandb-log-{label}",
        daemon=True,
    )
    thread.start()
    return thread


def _drain_iterable_to_queue(
    lines: Iterable[str],
    label: str,
    log_queue: queue.Queue,
) -> None:
    """Iterate *lines* and push ``(label, line)`` tuples to *log_queue*.

    Works with any iterable: ``stream_logs()`` readers (Cases 1 & 3) and
    the generator produced by ``CodeArtifactSource.start()`` (Case 2).
    """
    print(f"[DEBUG] _drain_iterable_to_queue: {label} drain thread starting")
    try:
        for line in lines:
            log_queue.put((label, line))
    except Exception as e:
        print(f"[DEBUG] _drain_iterable_to_queue: {label} drain thread exiting with {e!r}")
    print(f"[DEBUG] _drain_iterable_to_queue: {label} drain thread done")


def _printer_thread(log_queue: queue.Queue, label_width: int) -> None:
    """Drain *log_queue* and write docker-compose-style lines to stdout.

    A single thread owns all writes so lines from concurrent sandbox log
    threads are never interleaved.

    Format::

        agent-0  | some log line
        agent-1  | another log line
    """
    while True:
        item = log_queue.get()
        if item is _PRINTER_STOP:
            return
        label, line = item  # type: ignore[misc]
        try:
            index = int(label.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            index = 0
        colour = _LABEL_COLOURS[index % len(_LABEL_COLOURS)]
        sys.stdout.write(f"{colour}{label:<{label_width}}{_RESET}  | {line}\n")
        sys.stdout.flush()
