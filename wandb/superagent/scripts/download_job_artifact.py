#!/usr/bin/env python3
"""Download a W&B job-type artifact into a directory.

Standalone entrypoint for sandboxes with only PyPI ``wandb`` installed (no
``wandb.superagent``). Run::

    python download_job_artifact.py --job-artifact entity/project/my-job:latest --root /job

Requires ``WANDB_API_KEY`` (and optionally ``WANDB_BASE_URL``) in the environment.
"""

from __future__ import annotations

import argparse
import sys

from wandb.apis.public import Api
from wandb.errors import CommError


def _download(
    job_artifact_path: str,
    root: str,
    *,
    allow_missing_references: bool,
    skip_cache: bool | None,
) -> str:
    client = Api()
    try:
        artifact = client._artifact(job_artifact_path, type="job")
    except CommError:
        raise CommError(f"Job artifact {job_artifact_path!r} not found") from None
    return str(
        artifact.download(
            root=root,
            allow_missing_references=allow_missing_references,
            skip_cache=skip_cache,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download a job-type W&B artifact to a local directory."
    )
    parser.add_argument(
        "--job-artifact",
        required=True,
        help='Artifact path, e.g. "entity/project/my-job:v3" or "project/job:latest".',
    )
    parser.add_argument(
        "--root",
        required=True,
        help="Directory to download the artifact into (created if needed).",
    )
    parser.add_argument(
        "--allow-missing-references",
        action="store_true",
        help="Forward to Artifact.download (optional reference targets).",
    )
    parser.add_argument(
        "--skip-cache",
        action="store_true",
        help="Skip artifact cache when downloading.",
    )
    args = parser.parse_args(argv)

    try:
        out = _download(
            args.job_artifact,
            args.root,
            allow_missing_references=args.allow_missing_references,
            skip_cache=True if args.skip_cache else None,
        )
    except CommError as e:
        print(f"download_job_artifact failed: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"download_job_artifact failed: {e}", file=sys.stderr)
        return 1

    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
