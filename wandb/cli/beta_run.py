"""Shared submission layer for ``wandb beta run`` and ``wandb beta eval``.

Both CLI commands call :func:`submit_sandbox_job`, which packages
parameters into the launch config convention
(``{"overrides": {"run_config": ...}}``) and submits via
:func:`launch_add`.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import PurePosixPath
from typing import Any

import wandb
import wandb.apis.public as public

# Launch job artifact reference for the sandbox executor.
# The sandbox job image is a thin container (aviato + wandb) that reads
# config from launch and delegates to Sandbox.run().
# Override with WANDB_SANDBOX_JOB env var to use a different job artifact.
BASE_JOB = os.environ.get(
    "WANDB_SANDBOX_JOB",
    "wandb/test-jobs/launch_sandbox:latest",
)

# Launch job artifact reference for the eval executor.
# Override with WANDB_EVAL_JOB env var to use a different job artifact.
EVAL_JOB = os.environ.get(
    "WANDB_EVAL_JOB",
    "wandb/test-jobs/Test_evaluate_API-hosted_model:latest",
)

# Default container image used inside the sandbox for ``wandb beta run``.
DEFAULT_RUN_IMAGE = "python:3.11"
# Absolute directory inside the sandbox where mounted scripts are placed.
SANDBOX_WORKDIR = "/sandbox"


class SandboxConfigError(Exception):
    """Raised when user-supplied sandbox configuration is invalid."""


def _parse_env(
    env: list[str] | None = None,
) -> dict[str, str]:
    """Merge ``KEY=VAL`` env strings into one env dict."""
    merged: dict[str, str] = {}
    for item in env or []:
        if "=" not in item:
            raise SandboxConfigError(f"Expected KEY=VAL format for env, got: {item!r}")
        k, v = item.split("=", 1)
        merged[k] = v
    return merged


def _parse_secrets(
    secrets: list[str] | None = None,
) -> dict[str, str]:
    """Parse ``[DESTINATION_ENV_VAR:]SECRET_KEY_NAME`` specs.

    If no colon is provided the secret key name is used as both the
    destination env var and the W&B secret name.  With a colon the
    left side is the destination env var and the right side is the
    secret name.
    """
    merged: dict[str, str] = {}
    for item in secrets or []:
        if not item:
            raise SandboxConfigError("Secret spec must not be empty")
        if ":" in item:
            dest, key = item.split(":", 1)
            if not dest or not key:
                raise SandboxConfigError(
                    f"Both DESTINATION_ENV_VAR and SECRET_KEY_NAME must be non-empty, got: {item!r}"
                )
        else:
            dest = key = item
        merged[dest] = key
    return merged


def _parse_resources(resources: str | None) -> dict[str, Any] | None:
    """Parse a JSON string into a resources dict."""
    if resources is None:
        return None
    try:
        parsed = json.loads(resources)
    except json.JSONDecodeError as exc:
        raise SandboxConfigError("Invalid JSON for resources") from exc
    if not isinstance(parsed, dict):
        raise SandboxConfigError(
            "Resources JSON must be an object mapping string keys to values"
        )
    return parsed


def _split_mount_spec(spec: str) -> tuple[str, str]:
    r"""Split ``LOCAL_PATH[:SANDBOX_PATH]``.

    If no colon is provided the file is mounted at
    ``SANDBOX_WORKDIR/<basename>``.  With a colon the left side is
    the local path and the right side is the sandbox path.

    Uses :func:`os.path.splitdrive` so that a drive-letter colon
    (e.g. ``C:\\data\\file.py:/sandbox/file.py``) is not mistaken for
    the separator.
    """
    drive, rest = os.path.splitdrive(spec)
    if ":" in rest:
        local_suffix, sandbox_path = rest.split(":", 1)
        return drive + local_suffix, sandbox_path
    return spec, f"{SANDBOX_WORKDIR}/{os.path.basename(spec)}"


def _validate_sandbox_path(sandbox_path: str) -> None:
    """Validate sandbox paths are absolute, non-root, and free of ``..`` traversal."""
    normalized = sandbox_path.replace("\\", "/")
    if not normalized.startswith("/"):
        raise SandboxConfigError(
            f"Sandbox path must be absolute (start with '/'): {sandbox_path!r}"
        )
    if normalized == "/" or normalized.endswith("/"):
        raise SandboxConfigError(
            f"Sandbox path must point to a file, not a directory: {sandbox_path!r}"
        )
    if ".." in PurePosixPath(normalized).parts:
        raise SandboxConfigError(
            f"Sandbox path must not contain '..': {sandbox_path!r}"
        )


def script_sandbox_path(script: str) -> str:
    """Return the absolute sandbox path for a script (``SANDBOX_WORKDIR/<basename>``)."""
    return f"{SANDBOX_WORKDIR}/{os.path.basename(script)}"


def _parse_mounts(
    script: str,
    mounts: list[str] | None = None,
) -> tuple[dict[str, str], str]:
    """Resolve the script and ``--mount`` specs into ``{abs_local_path: sandbox_path}``.

    The script is always included and mounted at
    ``SANDBOX_WORKDIR/<basename>``.  Each mount spec follows the
    ``LOCAL_PATH[:SANDBOX_PATH]`` convention — if no colon is provided
    the file is mounted at ``SANDBOX_WORKDIR/<basename>``.  Local
    paths are normalised to absolute paths.

    Returns ``(local_to_remote, script_sandbox_path)`` so the caller
    can reference the script's sandbox location in command args.

    Raises :exc:`SandboxConfigError` if any file doesn't exist or a
    sandbox path contains ``..``.
    """
    script_norm = os.path.realpath(os.path.expanduser(script))
    if not os.path.isfile(script_norm):
        raise SandboxConfigError(f"Script not found: {script}")

    script_sandbox = script_sandbox_path(script_norm)
    _validate_sandbox_path(script_sandbox)
    local_to_remote: dict[str, str] = {script_norm: script_sandbox}
    remote_paths: set[str] = {script_sandbox}
    for spec in mounts or []:
        local_path, sandbox_path = _split_mount_spec(spec)
        local_norm = os.path.realpath(os.path.expanduser(local_path))

        if not os.path.isfile(local_norm):
            raise SandboxConfigError(f"Mount file not found: {local_path}")
        if local_norm in local_to_remote:
            raise SandboxConfigError(
                f"Local file {local_path!r} is already mounted at "
                f"{local_to_remote[local_norm]!r}"
            )
        if sandbox_path in remote_paths:
            raise SandboxConfigError(
                f"Duplicate sandbox path {sandbox_path!r} — "
                f"multiple local files cannot map to the same destination"
            )
        _validate_sandbox_path(sandbox_path)

        local_to_remote[local_norm] = sandbox_path
        remote_paths.add(sandbox_path)
    return local_to_remote, script_sandbox


def upload_files_artifact(
    local_to_remote: dict[str, str],
    *,
    project: str | None = None,
    entity: str | None = None,
) -> str:
    """Upload local files as a W&B artifact and return a qualified reference.

    Sandbox paths are absolute (e.g. ``/etc/config.json``).  The leading
    ``/`` is stripped when creating artifact entry names so that
    ``artifact.download(root)`` places files under *root* correctly.
    The executor reconstructs the absolute mount path by prepending ``/``.

    Returns ``entity/project/artifact_name:version``.
    """
    name = f"sandbox-files-{uuid.uuid4().hex[:8]}"
    artifact = wandb.Artifact(name=name, type="sandbox-files")
    for local_path, sandbox_path in local_to_remote.items():
        artifact.add_file(local_path, name=sandbox_path.lstrip("/"))

    with wandb.init(
        entity=entity,
        project=project,
        job_type="auto",
        settings=wandb.Settings(silent=True),
    ) as run:
        run.log_artifact(artifact)

    artifact.wait()
    return f"{run.entity}/{run.project}/{artifact.name}"


def submit_sandbox_job(
    *,
    job: str = BASE_JOB,
    command: str | None = None,
    args: list[str] | None = None,
    image: str = DEFAULT_RUN_IMAGE,
    env: list[str] | None = None,
    resources: str | None = None,
    timeout: int | None = None,
    script: str | None = None,
    mounts: list[str] | None = None,
    tags: list[str] | None = None,
    tower_ids: list[str] | None = None,
    project: str | None = None,
    entity: str | None = None,
    entity_name: str | None = None,
    queue: str | None = None,
    secrets: dict[str, str] | None = None,
    dry_run: bool = False,
) -> public.QueuedRun | dict[str, Any] | None:
    """Package parameters into a launch run config and submit via :func:`launch_add`.

    Handles several concerns before submission:

    - ``env`` (``KEY=VAL``) strings are placed into
      ``run_config["env_vars"]``.
    - ``WANDB_PROJECT``/``WANDB_ENTITY``/``WANDB_ENTITY_NAME`` are
      auto-injected unless already provided via ``--env``.
    - Secrets passed via *secrets* (``{dest_env_var: secret_key_name}``)
      are expanded into ``secret://`` config fields, resolved at runtime.
    - If *script* is given, it and any *mounts* are uploaded as a
      W&B artifact keyed by sandbox paths; only the artifact reference
      is sent in the config.

    When *dry_run* is True, returns the config dict instead of submitting.
    """
    from wandb.sdk.launch import launch_add

    if args and command is None:
        raise SandboxConfigError(
            "Cannot provide args without a command — set 'command' or remove 'args'"
        )

    files_artifact: str | None = None
    if script is not None:
        local_to_sandbox, _ = _parse_mounts(script, mounts)
        if dry_run:
            files_artifact = f"<pending upload: {local_to_sandbox}>"
        else:
            files_artifact = upload_files_artifact(
                local_to_sandbox, project=project, entity=entity
            )

    env = list(env or [])
    user_env_keys = {item.split("=", 1)[0] for item in env if "=" in item}
    if project and "WANDB_PROJECT" not in user_env_keys:
        env.append(f"WANDB_PROJECT={project}")
    if entity and "WANDB_ENTITY" not in user_env_keys:
        env.append(f"WANDB_ENTITY={entity}")
    if entity_name and "WANDB_ENTITY_NAME" not in user_env_keys:
        env.append(f"WANDB_ENTITY_NAME={entity_name}")

    run_config: dict[str, Any] = {"image": image}
    for key, val in {
        "command": command,
        "args": args,
        "env_vars": _parse_env(env),
        "resources": _parse_resources(resources),
        "timeout": timeout,
        "files_artifact": files_artifact,
        "tags": tags,
        "tower_ids": tower_ids,
    }.items():
        if val is not None:
            run_config[key] = val

    for field, secret_name in (secrets or {}).items():
        if field in run_config:
            raise SandboxConfigError(
                f"Secret destination {field!r} collides with a run config key"
            )
        run_config[field] = f"secret://{secret_name}"

    config = {"overrides": {"run_config": run_config}}

    if dry_run:
        return config

    return launch_add(
        job=job,
        config=config,
        project=project,
        entity=entity,
        queue_name=queue,
    )
