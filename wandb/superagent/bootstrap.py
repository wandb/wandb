"""Sandbox-side bootstrap: fetch job source (code artifact or git) into a workspace.

Expects the W&B **job artifact** to already be on disk at ``JOB_ARTIFACT_DIR``
(default ``/job``), e.g. after ``download_job_artifact.py`` in the sandbox.

**In a full checkout** (editable install)::

    python -m wandb.superagent.bootstrap --workspace /workspace

**With only PyPI ``wandb``** (no ``wandb.superagent`` package), copy this single file
into the container and run::

    pip install wandb
    python bootstrap.py --workspace /workspace

This module inlines the small helpers that used to live in ``job.py`` so the script
does not import ``wandb.superagent.*``. All other dependencies are the public SDK
(``Api``, ``util``, launch helpers, etc.).

Requires ``WANDB_API_KEY`` (and optionally ``WANDB_BASE_URL``) for code-artifact jobs;
git credentials in the environment for private ``repo`` jobs. Image-based jobs no-op.

Dependency installation is **not** done here: the host (e.g. ``wandb.superagent.main``)
runs ``sandbox.exec`` for ``pip install -r …/requirements.frozen.txt`` after bootstrap
when appropriate.
"""

from __future__ import annotations

import argparse
import enum
import json
import os
import shutil
import sys
from collections.abc import Mapping
from typing import Any

import wandb
from wandb import util
from wandb.apis.public import Api
from wandb.errors import CommError
from wandb.sdk.artifacts.artifact_state import ArtifactState
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import _fetch_git_repo, apply_patch
from wandb.sdk.lib.paths import FilePathStr, StrPath

# --- Inlined from ``job.py`` so this module runs with PyPI wandb + no superagent pkg ---

# Directory containing ``wandb-job.json`` after the job artifact download (must match
# the download script's ``--root``; superagent ``main`` uses ``/job`` in the sandbox).
JOB_ARTIFACT_DIR = "/job"


class JobSourceKind(str, enum.Enum):
    """How a job specifies runnable source (``wandb-job.json`` ``source_type``)."""

    ARTIFACT = "artifact"
    REPO = "repo"
    IMAGE = "image"


def load_job_spec(job_dir: StrPath) -> Mapping[str, Any]:
    """Load ``wandb-job.json`` from a downloaded job artifact directory."""
    job_json_path = os.path.join(os.fspath(job_dir), "wandb-job.json")
    if not os.path.isfile(job_json_path):
        raise FileNotFoundError(f"No wandb-job.json at {job_json_path}")
    with open(job_json_path, encoding="utf-8") as f:
        return json.load(f)


def job_source_kind_from_spec(spec: Mapping[str, Any]) -> JobSourceKind:
    """Return :class:`JobSourceKind` from a loaded job spec (``wandb-job.json`` body)."""
    raw = spec.get("source_type")
    if raw is None:
        raise ValueError("wandb-job.json missing source_type")
    if not isinstance(raw, str):
        raise TypeError(f"source_type must be a string, got {type(raw).__name__}")
    try:
        return JobSourceKind(raw)
    except ValueError:
        allowed = ", ".join(repr(m.value) for m in JobSourceKind)
        raise ValueError(
            f"unsupported source_type {raw!r}; expected one of {allowed}"
        ) from None


def download_job_source_artifact(
    job_dir: StrPath,
    *,
    root: StrPath | None = None,
    api: Api | None = None,
    allow_missing_references: bool = False,
    skip_cache: bool | None = None,
    path_prefix: StrPath | None = None,
    multipart: bool | None = None,
) -> FilePathStr:
    """Download the code artifact referenced by a job's ``wandb-job.json``."""
    job_info = load_job_spec(job_dir)
    source = job_info.get("source") or {}
    artifact_ref = source.get("artifact")
    if not artifact_ref or not isinstance(artifact_ref, str):
        raise LaunchError("Job wandb-job.json has no source.artifact string")

    name_or_id, _base_url, is_id = util.parse_artifact_string(artifact_ref)
    client = api if api is not None else Api()
    if is_id:
        code_artifact = wandb.Artifact._from_id(name_or_id, client.client)
    else:
        code_artifact = client._artifact(name=name_or_id, type="code")

    if code_artifact is None:
        raise LaunchError("No artifact found for job source.artifact reference")
    if code_artifact.state == ArtifactState.DELETED:
        raise LaunchError(f"Job references deleted code artifact {code_artifact.name}")

    return code_artifact.download(
        root=root,
        allow_missing_references=allow_missing_references,
        skip_cache=skip_cache,
        path_prefix=path_prefix,
        multipart=multipart,
    )


def bootstrap(
    workspace_dir: str,
    *,
    api: Api | None = None,
) -> str:
    """Populate ``workspace_dir`` from the job artifact at ``JOB_ARTIFACT_DIR``.

    For :attr:`JobSourceKind.ARTIFACT`, copies ``requirements.frozen.txt`` (if
    present) into the workspace then downloads the code artifact referenced by
    ``wandb-job.json``.

    For :attr:`JobSourceKind.REPO`, clones ``source.git.remote`` at
    ``source.git.commit``, applies ``diff.patch`` from the job artifact if present,
    then copies ``requirements.frozen.txt`` into the workspace.

    For :attr:`JobSourceKind.IMAGE`, does nothing (returns ``workspace_dir``).

    Args:
        workspace_dir: Directory where source code should be placed (created if
            needed for artifact/repo jobs).
        api: Optional :class:`~wandb.apis.public.Api` for artifact download.

    Returns:
        ``workspace_dir``.
    """
    job_root = os.fspath(JOB_ARTIFACT_DIR)
    workspace_dir = os.fspath(workspace_dir)

    spec = load_job_spec(job_root)
    kind = job_source_kind_from_spec(spec)

    if kind == JobSourceKind.IMAGE:
        return workspace_dir

    os.makedirs(workspace_dir, exist_ok=True)
    req_src = os.path.join(job_root, "requirements.frozen.txt")

    if kind == JobSourceKind.ARTIFACT:
        if os.path.isfile(req_src):
            shutil.copy2(
                req_src, os.path.join(workspace_dir, "requirements.frozen.txt")
            )
        download_job_source_artifact(
            job_dir=job_root,
            root=workspace_dir,
            api=api,
        )
        return workspace_dir

    if kind == JobSourceKind.REPO:
        git_info = (spec.get("source") or {}).get("git") or {}
        remote = git_info.get("remote")
        commit = git_info.get("commit")
        if not remote:
            raise LaunchError("repo job missing source.git.remote")
        _fetch_git_repo(workspace_dir, remote, commit)
        diff_path = os.path.join(job_root, "diff.patch")
        if os.path.isfile(diff_path):
            with open(diff_path, encoding="utf-8") as f:
                apply_patch(f.read(), workspace_dir)
        if os.path.isfile(req_src):
            shutil.copy2(
                req_src, os.path.join(workspace_dir, "requirements.frozen.txt")
            )
        return workspace_dir

    raise AssertionError(f"unhandled JobSourceKind: {kind!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap workspace from a W&B job artifact directory."
    )
    parser.add_argument(
        "--workspace",
        default="/workspace",
        help="Directory to populate with source (default: /workspace).",
    )
    args = parser.parse_args(argv)

    try:
        bootstrap(args.workspace)
    except (CommError, LaunchError, OSError, TypeError, ValueError) as e:
        print(f"bootstrap failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
