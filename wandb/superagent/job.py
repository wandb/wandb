"""Utilities for W&B job artifacts.

Host-side helpers and re-exports. Logic shared with sandbox bootstrap lives in
:mod:`wandb.superagent.bootstrap` so a single ``bootstrap.py`` can run with only
PyPI ``wandb`` installed (no ``wandb.superagent`` package in the environment).
"""

from __future__ import annotations

from wandb.apis.public import Api
from wandb.errors import CommError
from wandb.sdk.lib.paths import FilePathStr, StrPath

from wandb.superagent.bootstrap import (
    JobSourceKind,
    download_job_source_artifact,
    job_source_kind_from_spec,
    load_job_spec,
)


def download_job_artifact(
    job_artifact_path: str,
    *,
    root: StrPath | None = None,
    api: Api | None = None,
    allow_missing_references: bool = False,
    skip_cache: bool | None = None,
    path_prefix: StrPath | None = None,
    multipart: bool | None = None,
) -> FilePathStr:
    """Download a job-type W&B artifact to disk.

    This is the host-side entrypoint for materializing a job before sandbox or
    launch steps. The returned directory is the artifact root (see **On-disk
    layout**).

    Args:
        job_artifact_path: Artifact path accepted by the public API, for example
            ``entity/project/my-job:v3`` or ``project/my-job:latest``.
        root: Directory for downloaded files. If omitted, the default artifact
            download location is used (see ``wandb.Artifact.download``).
        api: Optional ``wandb.Api`` instance. Defaults to ``Api()``.
        allow_missing_references: Forwarded to ``Artifact.download``.
        skip_cache: Forwarded to ``Artifact.download``.
        path_prefix: Forwarded to ``Artifact.download``.
        multipart: Forwarded to ``Artifact.download``.

    Returns:
        Path to the downloaded artifact root directory.

    **On-disk layout** (typical):

        - ``wandb-job.json`` — job metadata (``source_type``, ``source``, …).
        - ``requirements.frozen.txt`` — pinned dependencies for the job.
        - ``diff.patch`` — optional; present for some ``repo`` jobs.

    Raises:
        CommError: If the artifact cannot be fetched (including when missing).
        ValueError: If the artifact exists but is not of type ``job``.
    """
    client = api if api is not None else Api()
    try:
        artifact = client._artifact(job_artifact_path, type="job")
    except CommError:
        raise CommError(f"Job artifact {job_artifact_path} not found")
    return artifact.download(
        root=root,
        allow_missing_references=allow_missing_references,
        skip_cache=skip_cache,
        path_prefix=path_prefix,
        multipart=multipart,
    )


def job_source_kind(job_dir: StrPath) -> JobSourceKind:
    """Infer source kind from a directory produced by :func:`download_job_artifact`."""
    return job_source_kind_from_spec(load_job_spec(job_dir))


__all__ = (
    "JobSourceKind",
    "download_job_artifact",
    "download_job_source_artifact",
    "job_source_kind",
    "job_source_kind_from_spec",
    "load_job_spec",
)
