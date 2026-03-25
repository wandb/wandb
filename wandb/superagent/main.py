"""Dev helper: download a job artifact on the host, inspect it, bootstrap in sandbox.

Edit the configuration block below, then run::

    python -m wandb.superagent.main

Requires ``WANDB_API_KEY`` (and network) when downloading or bootstrapping
artifact/repo jobs.

**Sandbox** uses ``wandb.sandbox.Sandbox``. On this repo install extras with::

    uv sync --extra sandbox

(or ``pip install -e '.[sandbox]'``) so ``cwsandbox`` is available. Sandbox auth
uses provider env (e.g. ``CWSANDBOX``).

Inside the container the job is materialized under ``JOB_ARTIFACT_DIR`` (``/job``)
by uploading and running ``scripts/download_job_artifact.py`` (PyPI ``wandb`` only),
then ``bootstrap.py``. Workspace dependencies are installed with a separate
``sandbox.exec`` ``pip install -r …/requirements.frozen.txt`` when the file exists.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from wandb.errors import CommError
from wandb.sandbox import NetworkOptions, Process, ProcessResult, Sandbox
from wandb.superagent.bootstrap import JOB_ARTIFACT_DIR
from wandb.superagent.job import (
    JobSourceKind,
    download_job_artifact,
    job_source_kind,
    load_job_spec,
)

# ---------------------------------------------------------------------------
# Configuration — edit these values
# ---------------------------------------------------------------------------

# W&B job artifact path, e.g. ``entity/project/my-job:latest``.
JOB_ARTIFACT: str | None = (
    "wandb/hackathon-sweep-jobs/job-source-hackathon-sweep-jobs-train.py:latest"
)

SWEEP_COMMAND = ["wandb", "agent", "wandb/hackathon-sweep-cwagent/dxwfk9z1"]

# Host download root for ``download_job_artifact`` (default: artifact cache).
DOWNLOAD_ROOT: str | None = None

# If True, print ``wandb-job.json`` after loading.
PRINT_SPEC = False

# --- Sandbox (``wandb.sandbox.Sandbox``) ---
# Container image when the job is not ``image``-sourced, or when you want to
# override. ``image`` jobs use ``source.image`` from ``wandb-job.json`` when
# this is None.
SANDBOX_DEFAULT_IMAGE = "python:3.11-slim"

SANDBOX_REMOTE_WORKSPACE = "/workspace"
SANDBOX_REMOTE_DOWNLOAD_SCRIPT = "/tmp/wandb_superagent_download_job.py"
SANDBOX_REMOTE_BOOTSTRAP_SCRIPT = "/tmp/wandb_superagent_bootstrap.py"

SANDBOX_IDLE_COMMAND = "sleep"
SANDBOX_IDLE_ARGS: list[str] = ["infinity"]

# ``pip install <spec>`` in the sandbox before download + bootstrap (e.g. ``wandb``).
SANDBOX_PYPI_WANDB_SPEC = "wandb"


def _stream_exec_stdout_and_wait(
    proc: Process,
    *,
    sandbox_id: str | None = None,
) -> ProcessResult:
    """Stream ``proc.stdout`` line-by-line, then return ``proc.result()``."""
    label = sandbox_id[-6:] if sandbox_id else ""
    prefix = f"[{label}] " if label else "[sandbox] "
    for line in proc.stdout:
        print(prefix + line, end="")
    return proc.result()


def _download_job_script_bytes() -> bytes:
    return (
        Path(__file__).resolve().parent / "scripts" / "download_job_artifact.py"
    ).read_bytes()


def _local_bootstrap_script_bytes() -> bytes:
    return (Path(__file__).resolve().parent / "bootstrap.py").read_bytes()


def _sandbox_env() -> dict[str, str]:
    key = os.environ.get("WANDB_API_KEY")
    if not key:
        raise ValueError("WANDB_API_KEY is required for sandbox bootstrap")
    env: dict[str, str] = {"WANDB_API_KEY": key}
    for name in ("WANDB_BASE_URL", "WANDB_ENTITY", "WANDB_PROJECT"):
        val = os.environ.get(name)
        if val:
            env[name] = val
    return env


def _sandbox_bootstrap(
    *,
    job_artifact_ref: str,
    container_image: str,
    install_dependencies: bool,
) -> int:
    with Sandbox(
        command=SANDBOX_IDLE_COMMAND,
        network=NetworkOptions(egress_mode="internet"),  # type: ignore[call-arg]
        args=SANDBOX_IDLE_ARGS,
        container_image=container_image,
        environment_variables=_sandbox_env(),
    ) as sandbox:
        sandbox.exec(["mkdir", "-p", JOB_ARTIFACT_DIR]).result()
        sandbox.exec(["mkdir", "-p", SANDBOX_REMOTE_WORKSPACE]).result()

        if spec := SANDBOX_PYPI_WANDB_SPEC.strip():
            print(f"pip install {spec!r} in sandbox …")
            pip_pub = _stream_exec_stdout_and_wait(
                sandbox.exec(
                    [
                        "python",
                        "-m",
                        "pip",
                        "install",
                        "--no-cache-dir",
                        "--upgrade",
                        spec,
                    ],
                ),
                sandbox_id=sandbox.sandbox_id,
            )
            if pip_pub.returncode != 0:
                print(
                    f"pip install {spec!r} exit {pip_pub.returncode}",
                    file=sys.stderr,
                )
                return pip_pub.returncode

        sandbox.write_file(
            SANDBOX_REMOTE_DOWNLOAD_SCRIPT,
            _download_job_script_bytes(),
        ).result()
        dl = _stream_exec_stdout_and_wait(
            sandbox.exec(
                [
                    "python",
                    SANDBOX_REMOTE_DOWNLOAD_SCRIPT,
                    "--job-artifact",
                    job_artifact_ref,
                    "--root",
                    JOB_ARTIFACT_DIR,
                ],
            ),
            sandbox_id=sandbox.sandbox_id,
        )
        if dl.returncode != 0:
            print(
                f"sandbox job download exit {dl.returncode}",
                file=sys.stderr,
            )
            return dl.returncode

        sandbox.write_file(
            SANDBOX_REMOTE_BOOTSTRAP_SCRIPT,
            _local_bootstrap_script_bytes(),
        ).result()
        result = _stream_exec_stdout_and_wait(
            sandbox.exec(
                [
                    "python",
                    SANDBOX_REMOTE_BOOTSTRAP_SCRIPT,
                    "--workspace",
                    SANDBOX_REMOTE_WORKSPACE,
                ],
            ),
            sandbox_id=sandbox.sandbox_id,
        )
        if result.returncode != 0:
            print(
                f"sandbox bootstrap exit {result.returncode}",
                file=sys.stderr,
            )
            return result.returncode
        print(
            f"sandbox bootstrap finished, source code is in {SANDBOX_REMOTE_WORKSPACE}"
        )

        if install_dependencies:
            req_remote = f"{SANDBOX_REMOTE_WORKSPACE}/requirements.txt"
            probe = sandbox.exec(["test", "-f", req_remote]).result()
            if probe.returncode == 0:
                print("pip installing dependencies in sandbox …")
                pip_ws = _stream_exec_stdout_and_wait(
                    sandbox.exec(
                        [
                            "python",
                            "-m",
                            "pip",
                            "install",
                            "--no-cache-dir",
                            "-r",
                            req_remote,
                        ],
                    ),
                    sandbox_id=sandbox.sandbox_id,
                )
                if pip_ws.returncode != 0:
                    print(
                        f"pip installing deps exit {pip_ws.returncode}",
                        file=sys.stderr,
                    )
                    return pip_ws.returncode

        sweep_result = _stream_exec_stdout_and_wait(
            sandbox.exec(SWEEP_COMMAND, cwd=SANDBOX_REMOTE_WORKSPACE),
            sandbox_id=sandbox.sandbox_id,
        )
        if sweep_result.returncode != 0:
            print(
                f"sweep command exit {sweep_result.returncode}",
                file=sys.stderr,
            )
            return sweep_result.returncode

    return 0


def _resolve_sandbox_image(spec: dict, kind: JobSourceKind) -> str:
    if kind == JobSourceKind.IMAGE:
        image = (spec.get("source") or {}).get("image")
        if isinstance(image, str) and image.strip():
            return image.strip()
    return SANDBOX_DEFAULT_IMAGE


def main() -> int:
    if not JOB_ARTIFACT:
        print(
            "Set JOB_ARTIFACT to a W&B job artifact path (e.g. entity/project/job:alias).",
            file=sys.stderr,
        )
        return 1

    print(f"Downloading job artifact on host: {JOB_ARTIFACT!r} …")
    try:
        job_root = download_job_artifact(
            JOB_ARTIFACT,
            root=DOWNLOAD_ROOT,
        )
    except CommError as e:
        print(f"Download failed: {e}", file=sys.stderr)
        return 1
    print(f"Downloaded to: {job_root}")

    try:
        spec = load_job_spec(job_root)
        kind = job_source_kind(job_root)
    except (FileNotFoundError, TypeError, ValueError) as e:
        print(f"Failed to read job spec: {e}", file=sys.stderr)
        return 1

    print(f"job_source_kind: {kind.value}")

    if PRINT_SPEC:
        print(json.dumps(spec, indent=2))

    # Install workspace deps by default; image-sourced jobs use a prebuilt image.
    install_deps = kind != JobSourceKind.IMAGE

    image = _resolve_sandbox_image(dict(spec), kind)
    print(f"Sandbox image: {image!r}")
    try:
        return _sandbox_bootstrap(
            job_artifact_ref=JOB_ARTIFACT,
            container_image=image,
            install_dependencies=install_deps,
        )
    except Exception as e:
        print(f"sandbox failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
