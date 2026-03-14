"""W&B-aware wrapper around `cwsandbox.Sandbox`.

The copied class-level RPC helpers here are intentional for now.

We chose wrapper subclasses over a process-wide monkeypatch of
`cwsandbox._sandbox.resolve_auth_metadata`. A monkeypatch would be smaller, but
it would also change the behavior of direct `cwsandbox.Sandbox` users in the
same process after `import wandb.sandbox`.

What upstream could do to make this wrapper much smaller:
- replace module-level auth lookups with protected overridable hooks for
  instance and class operations
- or accept explicit auth metadata/context in the internal async helpers
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import tempfile
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import grpc
from cwsandbox import NetworkOptions, OperationRef, Process, ProcessResult, StreamWriter
from cwsandbox import Sandbox as CWSandboxSandbox
from cwsandbox._defaults import (
    DEFAULT_BASE_URL,
    DEFAULT_GRACEFUL_SHUTDOWN_SECONDS,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    SandboxDefaults,
)
from cwsandbox._network import create_channel, parse_grpc_target
from cwsandbox._proto import atc_pb2, atc_pb2_grpc
from cwsandbox._sandbox import SandboxStatus, _translate_rpc_error
from cwsandbox.exceptions import SandboxError

import wandb
from wandb.sdk.wandb_run import TeardownHook, TeardownStage

from ._auth import SandboxAuthContext, _current_run, resolve_auth_context

logger = logging.getLogger(__name__)

_SANDBOX_LOG_ARTIFACT_TYPE = "sandbox-log"
_CAPTURE_LOG_DESTINATIONS = {"artifact", "run_file"}


class _CapturedStdinWriter(StreamWriter):
    """Proxy StreamWriter that mirrors stdin data into an in-memory transcript."""

    def __init__(self, inner: StreamWriter, sink: list[str]) -> None:
        self._inner = inner
        self._sink = sink
        self._sink_lock = threading.Lock()

    @property
    def closed(self) -> bool:
        return self._inner.closed

    def write(self, data: bytes) -> OperationRef[None]:
        op = self._inner.write(data)
        with self._sink_lock:
            self._sink.append(data.decode("utf-8", errors="replace"))
        return op

    def writeline(self, text: str, encoding: str = "utf-8") -> OperationRef[None]:
        op = self._inner.writeline(text, encoding=encoding)
        with self._sink_lock:
            self._sink.append(text + "\n")
        return op

    def close(self) -> OperationRef[None]:
        return self._inner.close()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _append_output_section(lines: list[str], label: str, value: str | None) -> None:
    lines.append(f"[{label}]\n")
    if value:
        lines.append(value)
        if not value.endswith("\n"):
            lines.append("\n")
        return
    lines.append("<empty>\n")


def _default_capture_artifact_name(run_id: str, sandbox_id: str | None) -> str:
    return f"sandbox-logs-{run_id}-{sandbox_id or 'pending'}"


class Sandbox(CWSandboxSandbox):
    """W&B-aware wrapper around `cwsandbox.Sandbox`."""

    def __init__(
        self,
        *,
        command: str | None = None,
        args: list[str] | None = None,
        defaults: SandboxDefaults | None = None,
        container_image: str | None = None,
        tags: list[str] | None = None,
        base_url: str | None = None,
        request_timeout_seconds: float | None = None,
        max_lifetime_seconds: float | None = None,
        runway_ids: list[str] | None = None,
        tower_ids: list[str] | None = None,
        resources: dict[str, Any] | None = None,
        mounted_files: list[dict[str, Any]] | None = None,
        s3_mount: dict[str, Any] | None = None,
        ports: list[dict[str, Any]] | None = None,
        network: NetworkOptions | dict[str, Any] | None = None,
        max_timeout_seconds: int | None = None,
        environment_variables: dict[str, str] | None = None,
        capture_logs: bool = True,
        capture_logs_to: str = "artifact",
        capture_artifact_name: str | None = None,
        _session=None,
    ) -> None:
        super().__init__(
            command=command,
            args=args,
            defaults=defaults,
            container_image=container_image,
            tags=tags,
            base_url=base_url,
            request_timeout_seconds=request_timeout_seconds,
            max_lifetime_seconds=max_lifetime_seconds,
            runway_ids=runway_ids,
            tower_ids=tower_ids,
            resources=resources,
            mounted_files=mounted_files,
            s3_mount=s3_mount,
            ports=ports,
            network=network,
            max_timeout_seconds=max_timeout_seconds,
            environment_variables=environment_variables,
            _session=_session,
        )
        self._init_wrapper_state(
            capture_logs=capture_logs,
            capture_logs_to=capture_logs_to,
            capture_artifact_name=capture_artifact_name,
        )

    def _init_wrapper_state(
        self,
        *,
        capture_logs: bool,
        capture_logs_to: str = "artifact",
        capture_artifact_name: str | None = None,
    ) -> None:
        if capture_logs_to not in _CAPTURE_LOG_DESTINATIONS:
            valid = ", ".join(sorted(_CAPTURE_LOG_DESTINATIONS))
            raise ValueError(
                f"capture_logs_to must be one of {{{valid}}}, got {capture_logs_to!r}"
            )
        self._wandb_auth_context: SandboxAuthContext | None = None
        self._capture_logs = capture_logs
        self._capture_logs_to = capture_logs_to
        self._capture_artifact_name = capture_artifact_name or None
        self._capture_lock = threading.Lock()
        self._capture_run = None
        self._capture_tempdir: tempfile.TemporaryDirectory[str] | None = None
        self._capture_dir: Path | None = None
        self._capture_initialized_at: str | None = None
        self._background_log_path: Path | None = None
        self._exec_log_path: Path | None = None
        self._background_reader = None
        self._background_thread: threading.Thread | None = None
        self._background_errors: list[BaseException] = []
        self._background_capture_started = False
        self._capture_hook_registered = False
        self._capture_finalized = False
        self._exec_log_lock = threading.Lock()
        self._exec_header_written = False

    @classmethod
    def _from_sandbox_info(
        cls,
        info,
        *,
        base_url: str,
        timeout_seconds: float,
    ) -> Sandbox:
        sandbox = super()._from_sandbox_info(
            info,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
        sandbox._init_wrapper_state(
            capture_logs=False,
            capture_logs_to="artifact",
            capture_artifact_name=None,
        )
        return sandbox

    @classmethod
    def run(
        cls,
        *args: str,
        container_image: str | None = None,
        defaults: SandboxDefaults | None = None,
        request_timeout_seconds: float | None = None,
        max_lifetime_seconds: float | None = None,
        tags: list[str] | None = None,
        runway_ids: list[str] | None = None,
        tower_ids: list[str] | None = None,
        resources: dict[str, Any] | None = None,
        mounted_files: list[dict[str, Any]] | None = None,
        s3_mount: dict[str, Any] | None = None,
        ports: list[dict[str, Any]] | None = None,
        network: NetworkOptions | dict[str, Any] | None = None,
        max_timeout_seconds: int | None = None,
        environment_variables: dict[str, str] | None = None,
        capture_logs: bool = True,
        capture_logs_to: str = "artifact",
        capture_artifact_name: str | None = None,
    ) -> Sandbox:
        command = args[0] if args else None
        cmd_args = list(args[1:]) if len(args) > 1 else None

        sandbox = cls(
            command=command,
            args=cmd_args,
            container_image=container_image,
            defaults=defaults,
            request_timeout_seconds=request_timeout_seconds,
            max_lifetime_seconds=max_lifetime_seconds,
            tags=tags,
            runway_ids=runway_ids,
            tower_ids=tower_ids,
            resources=resources,
            mounted_files=mounted_files,
            s3_mount=s3_mount,
            ports=ports,
            network=network,
            max_timeout_seconds=max_timeout_seconds,
            environment_variables=environment_variables,
            capture_logs=capture_logs,
            capture_logs_to=capture_logs_to,
            capture_artifact_name=capture_artifact_name,
        )
        logger.debug("Creating sandbox with command: %s", command)
        sandbox.start().result()
        return sandbox

    @classmethod
    def session(
        cls,
        defaults: SandboxDefaults | None = None,
    ):
        from ._session import Session

        return Session(defaults)

    def _ensure_capture_context(self) -> bool:
        if not self._capture_logs or self._capture_finalized:
            return False

        run = self._capture_run or _current_run()
        if run is None:
            return False

        with self._capture_lock:
            if not self._capture_logs or self._capture_finalized:
                return False
            if self._capture_run is None:
                self._capture_run = run
            if self._capture_tempdir is None:
                self._capture_tempdir = tempfile.TemporaryDirectory(
                    prefix="wandb-sandbox-log-"
                )
                self._capture_dir = Path(self._capture_tempdir.name)
                self._capture_initialized_at = _utc_now()
                self._background_log_path = self._capture_dir / "sandbox-background.log"
                self._exec_log_path = self._capture_dir / "sandbox-execs.txt"
            if not self._capture_hook_registered and hasattr(run, "_teardown_hooks"):
                run._teardown_hooks.append(
                    TeardownHook(self._finalize_log_capture, TeardownStage.EARLY)
                )
                self._capture_hook_registered = True
        return True

    def _maybe_start_log_capture(self) -> None:
        if not self._ensure_capture_context():
            return
        if self._sandbox_id is None or self._is_done:
            return

        with self._capture_lock:
            if (
                self._background_capture_started
                or self._sandbox_id is None
                or self._is_done
                or self._background_log_path is None
            ):
                return
            reader = super().stream_logs(follow=True, timestamps=True)
            thread = threading.Thread(
                target=self._write_background_logs,
                args=(reader, self._background_log_path),
                daemon=True,
                name=f"wandb-sandbox-log-{self._sandbox_id}",
            )
            self._background_reader = reader
            self._background_thread = thread
            self._background_capture_started = True
            thread.start()

    def _write_background_logs(self, reader, output_path: Path) -> None:
        try:
            with output_path.open("w", encoding="utf-8") as log_file:
                log_file.write("# Sandbox background log stream\n")
                log_file.write("# Source: Sandbox.stream_logs(follow=True)\n")
                log_file.write(f"# sandbox_id: {self.sandbox_id}\n\n")
                log_file.flush()
                for line in reader:
                    log_file.write(line)
                    if not line.endswith("\n"):
                        log_file.write("\n")
                    log_file.flush()
        except BaseException as exc:
            self._background_errors.append(exc)

    def _maybe_backfill_background_logs(self) -> None:
        if self._background_log_path is None:
            return

        needs_backfill = not self._background_log_path.exists()
        if not needs_backfill and self._background_log_path.stat().st_size <= 128:
            needs_backfill = True
        if not needs_backfill and self._background_errors:
            needs_backfill = True
        if not needs_backfill:
            return

        try:
            reader = super().stream_logs(follow=False, timestamps=True)
        except Exception as exc:
            self._background_errors.append(exc)
            return

        try:
            with self._background_log_path.open("w", encoding="utf-8") as log_file:
                log_file.write("# Sandbox background log stream\n")
                log_file.write("# Source: Sandbox.stream_logs(follow=False)\n")
                log_file.write(f"# sandbox_id: {self.sandbox_id}\n\n")
                log_file.flush()
                for line in reader:
                    log_file.write(line)
                    if not line.endswith("\n"):
                        log_file.write("\n")
        except BaseException as exc:
            self._background_errors.append(exc)
        finally:
            reader.close()

    def _append_exec_transcript(self, lines: list[str]) -> None:
        if self._exec_log_path is None:
            return
        with self._exec_log_lock:
            with self._exec_log_path.open("a", encoding="utf-8") as transcript:
                if not self._exec_header_written:
                    transcript.write("# Sandbox exec transcript\n")
                    transcript.write("# Source: Sandbox.exec(...)\n")
                    transcript.write(f"# sandbox_id: {self.sandbox_id}\n")
                    transcript.write(
                        f"# capture_started_at: {self._capture_initialized_at or _utc_now()}\n"
                    )
                    self._exec_header_written = True
                transcript.writelines(lines)
                transcript.flush()

    def _record_exec_completion(
        self,
        future,
        command: list[str],
        cwd: str | None,
        stdin_chunks: list[str],
    ) -> None:
        if self._capture_finalized or not self._ensure_capture_context():
            return

        lines = [
            f"\n=== EXEC {_utc_now()} ===\n",
            f"$ {' '.join(shlex.quote(part) for part in command)}\n",
        ]
        if cwd is not None:
            lines.append(f"[cwd] {cwd}\n")
        if stdin_chunks:
            _append_output_section(lines, "stdin", "".join(stdin_chunks))

        try:
            result = future.result()
        except Exception as exc:
            exec_result = getattr(exc, "exec_result", None)
            if isinstance(exec_result, ProcessResult):
                _append_output_section(lines, "stdout", exec_result.stdout)
                _append_output_section(lines, "stderr", exec_result.stderr)
                lines.append(f"[returncode] {exec_result.returncode}\n")
            lines.append(f"[exception] {type(exc).__name__}: {exc}\n")
        else:
            _append_output_section(lines, "stdout", result.stdout)
            _append_output_section(lines, "stderr", result.stderr)
            lines.append(f"[returncode] {result.returncode}\n")

        try:
            self._append_exec_transcript(lines)
        except Exception as exc:
            logger.warning(
                "Failed to append exec transcript for sandbox %s: %s",
                self.sandbox_id,
                exc,
            )

    def _save_log_files_to_run(self) -> bool:
        if self._capture_run is None:
            return True
        if getattr(self._capture_run, "_is_finished", False):
            logger.warning(
                "Skipping sandbox log run-file upload for %s because run %s is already finished",
                self.sandbox_id,
                self._capture_run.id,
            )
            return False

        paths_to_save: list[Path] = []
        if self._background_log_path is not None and self._background_log_path.exists():
            paths_to_save.append(self._background_log_path)
        if self._exec_log_path is not None and self._exec_log_path.exists():
            paths_to_save.append(self._exec_log_path)
        if not paths_to_save or self._capture_dir is None:
            return True

        try:
            run_files_dir = Path(self._capture_run.dir)
            for path in paths_to_save:
                staged_path = run_files_dir / path.name
                staged_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, staged_path)
                self._capture_run.save(
                    str(staged_path),
                    base_path=str(run_files_dir),
                    policy="now",
                )
        except Exception as exc:
            logger.warning(
                "Failed to save sandbox logs for %s as run files on run %s: %s",
                self.sandbox_id,
                self._capture_run.id,
                exc,
            )
            return False
        return True

    def _upload_log_artifact(self) -> bool:
        if self._capture_run is None:
            return True
        if getattr(self._capture_run, "_is_finished", False):
            logger.warning(
                "Skipping sandbox log upload for %s because run %s is already finished",
                self.sandbox_id,
                self._capture_run.id,
            )
            return False

        files_to_upload: list[Path] = []
        if self._background_log_path is not None and self._background_log_path.exists():
            files_to_upload.append(self._background_log_path)
        if self._exec_log_path is not None and self._exec_log_path.exists():
            files_to_upload.append(self._exec_log_path)
        if not files_to_upload:
            return True

        artifact = wandb.Artifact(
            self._capture_artifact_name
            or _default_capture_artifact_name(self._capture_run.id, self.sandbox_id),
            type=_SANDBOX_LOG_ARTIFACT_TYPE,
            metadata={
                "sandbox_id": self.sandbox_id,
                "background_log_file": self._background_log_path.name
                if self._background_log_path is not None
                else None,
                "exec_log_file": self._exec_log_path.name
                if self._exec_log_path is not None
                else None,
            },
        )
        for path in files_to_upload:
            artifact.add_file(str(path), name=path.name)

        try:
            self._capture_run.log_artifact(artifact)
        except Exception as exc:
            logger.warning(
                "Failed to upload sandbox logs for %s to run %s: %s",
                self.sandbox_id,
                self._capture_run.id,
                exc,
            )
            return False
        return True

    def _persist_captured_logs(self) -> bool:
        if self._capture_logs_to == "run_file":
            return self._save_log_files_to_run()
        return self._upload_log_artifact()

    def _cleanup_capture_tempdir(self) -> None:
        if self._capture_tempdir is None:
            return
        self._capture_tempdir.cleanup()
        self._capture_tempdir = None
        self._capture_dir = None
        self._background_log_path = None
        self._exec_log_path = None

    def _finalize_log_capture(self) -> None:
        with self._capture_lock:
            if self._capture_finalized:
                return
            self._capture_finalized = True
            reader = self._background_reader
            thread = self._background_thread
            self._background_reader = None
            self._background_thread = None

        if reader is not None:
            reader.close()
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning(
                    "Background sandbox log thread for %s did not shut down cleanly",
                    self.sandbox_id,
                )

        self._maybe_backfill_background_logs()
        if self._background_errors:
            logger.warning(
                "Encountered %d sandbox log capture error(s) for %s",
                len(self._background_errors),
                self.sandbox_id,
            )

        if self._persist_captured_logs():
            self._cleanup_capture_tempdir()
        elif self._capture_dir is not None:
            logger.warning(
                "Leaving sandbox log capture files for %s at %s",
                self.sandbox_id,
                self._capture_dir,
            )

    async def _start_async(self) -> str:
        sandbox_id = await super()._start_async()
        self._maybe_start_log_capture()
        return sandbox_id

    async def _ensure_client(self) -> None:
        if self._channel is not None:
            return

        # Instance operations are the one place where we can cheaply bind a
        # stable auth context to this sandbox without patching `cwsandbox`
        # process-wide.
        context = self._wandb_auth_context or resolve_auth_context()
        self._wandb_auth_context = context

        target, is_secure = parse_grpc_target(self._base_url)
        channel = create_channel(target, is_secure)
        stub = atc_pb2_grpc.ATCServiceStub(channel)  # type: ignore[no-untyped-call]
        self._channel = channel
        self._stub = stub
        self._auth_metadata = context.metadata
        logger.debug("Initialized W&B sandbox gRPC channel for %s", self._base_url)

    def exec(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
        check: bool = False,
        timeout_seconds: float | None = None,
        stdin: bool = False,
    ) -> Process:
        self._maybe_start_log_capture()
        process = super().exec(
            command,
            cwd=cwd,
            check=check,
            timeout_seconds=timeout_seconds,
            stdin=stdin,
        )
        if not self._capture_logs or self._capture_finalized:
            return process

        command_snapshot = list(command)
        stdin_chunks: list[str] = []
        if process.stdin is not None:
            process.stdin = _CapturedStdinWriter(process.stdin, stdin_chunks)

        process._future.add_done_callback(
            lambda future: self._record_exec_completion(
                future,
                command_snapshot,
                cwd,
                stdin_chunks,
            )
        )
        return process

    def stop(
        self,
        *,
        snapshot_on_stop: bool = False,
        graceful_shutdown_seconds: float = DEFAULT_GRACEFUL_SHUTDOWN_SECONDS,
        missing_ok: bool = False,
    ) -> OperationRef[None]:
        async def _stop_and_capture() -> None:
            try:
                await CWSandboxSandbox._stop_async(
                    self,
                    snapshot_on_stop=snapshot_on_stop,
                    graceful_shutdown_seconds=graceful_shutdown_seconds,
                    missing_ok=missing_ok,
                )
            finally:
                self._finalize_log_capture()

        future = self._loop_manager.run_async(_stop_and_capture())
        return OperationRef(future)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self._finalize_log_capture()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        try:
            await super().__aexit__(exc_type, exc_val, exc_tb)
        finally:
            self._finalize_log_capture()

    @classmethod
    async def _list_async(
        cls,
        *,
        tags: list[str] | None = None,
        status: str | None = None,
        runway_ids: list[str] | None = None,
        tower_ids: list[str] | None = None,
        include_stopped: bool = False,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> list[Sandbox]:
        # Upstream resolves auth inside this method body via a module-level
        # helper, so we currently need a local override to avoid a global patch.
        effective_base_url = (
            base_url or os.environ.get("CWSANDBOX_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else DEFAULT_REQUEST_TIMEOUT_SECONDS
        )

        status_enum = SandboxStatus(status) if status is not None else None
        auth_context = resolve_auth_context()
        auth_metadata = auth_context.metadata

        target, is_secure = parse_grpc_target(effective_base_url)
        channel = create_channel(target, is_secure)
        stub = atc_pb2_grpc.ATCServiceStub(channel)  # type: ignore[no-untyped-call]

        try:
            request_kwargs: dict[str, Any] = {}
            if tags:
                request_kwargs["tags"] = tags
            if status_enum:
                request_kwargs["status"] = status_enum.to_proto()
            if runway_ids is not None:
                request_kwargs["runway_ids"] = runway_ids
            if tower_ids is not None:
                request_kwargs["tower_ids"] = tower_ids
            if include_stopped:
                request_kwargs["include_stopped"] = True

            request = atc_pb2.ListSandboxesRequest(**request_kwargs)
            try:
                response = await stub.List(
                    request, timeout=timeout, metadata=auth_metadata
                )
            except grpc.RpcError as exc:
                raise _translate_rpc_error(exc, operation="List sandboxes") from exc

            sandboxes = [
                cls._from_sandbox_info(
                    sb,
                    base_url=effective_base_url,
                    timeout_seconds=timeout,
                )
                for sb in response.sandboxes
            ]
            for sandbox in sandboxes:
                sandbox._wandb_auth_context = auth_context
            return sandboxes
        finally:
            await channel.close(grace=None)

    @classmethod
    async def _from_id_async(
        cls,
        sandbox_id: str,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Sandbox:
        # Same reason as `_list_async`: upstream has no class-level auth hook
        # for this path yet, so we override the RPC entry point locally.
        effective_base_url = (
            base_url or os.environ.get("CWSANDBOX_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else DEFAULT_REQUEST_TIMEOUT_SECONDS
        )

        auth_context = resolve_auth_context()
        auth_metadata = auth_context.metadata

        target, is_secure = parse_grpc_target(effective_base_url)
        channel = create_channel(target, is_secure)
        stub = atc_pb2_grpc.ATCServiceStub(channel)  # type: ignore[no-untyped-call]

        try:
            request = atc_pb2.GetSandboxRequest(sandbox_id=sandbox_id)
            try:
                response = await stub.Get(
                    request, timeout=timeout, metadata=auth_metadata
                )
            except grpc.RpcError as exc:
                raise _translate_rpc_error(
                    exc, sandbox_id=sandbox_id, operation="Get sandbox"
                ) from exc

            sandbox = cls._from_sandbox_info(
                response,
                base_url=effective_base_url,
                timeout_seconds=timeout,
            )
            sandbox._wandb_auth_context = auth_context
            return sandbox
        finally:
            await channel.close(grace=None)

    @classmethod
    async def _delete_async(
        cls,
        sandbox_id: str,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        missing_ok: bool = False,
    ) -> None:
        # Same reason as `_list_async`: without an upstream hook, class-level
        # auth-sensitive operations need a wrapper-side override.
        effective_base_url = (
            base_url or os.environ.get("CWSANDBOX_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else DEFAULT_REQUEST_TIMEOUT_SECONDS
        )

        auth_metadata = resolve_auth_context().metadata

        target, is_secure = parse_grpc_target(effective_base_url)
        channel = create_channel(target, is_secure)
        stub = atc_pb2_grpc.ATCServiceStub(channel)  # type: ignore[no-untyped-call]

        try:
            request = atc_pb2.DeleteSandboxRequest(sandbox_id=sandbox_id)
            try:
                response = await stub.Delete(
                    request, timeout=timeout, metadata=auth_metadata
                )
            except grpc.RpcError as exc:
                if exc.code() == grpc.StatusCode.NOT_FOUND and missing_ok:
                    return
                raise _translate_rpc_error(
                    exc, sandbox_id=sandbox_id, operation="Delete sandbox"
                ) from exc

            if not response.success:
                raise SandboxError(
                    f"Failed to delete sandbox: {response.error_message}"
                )
        finally:
            await channel.close(grace=None)
