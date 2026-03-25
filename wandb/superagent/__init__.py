"""Superagent support code."""

from __future__ import annotations

from typing import Any

from wandb.superagent.job import (
    JobSourceKind,
    download_job_artifact,
    download_job_source_artifact,
    job_source_kind,
    job_source_kind_from_spec,
    load_job_spec,
)

__all__ = (
    "JobSourceKind",
    "bootstrap",
    "download_job_artifact",
    "download_job_source_artifact",
    "job_source_kind",
    "job_source_kind_from_spec",
    "load_job_spec",
)


def __getattr__(name: str) -> Any:
    if name == "bootstrap":
        from wandb.superagent.bootstrap import bootstrap as bootstrap_fn

        return bootstrap_fn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
