"""Manages artifact file staging.

Artifact files are copied to the staging area as soon as they are added to an artifact
in order to avoid file changes corrupting the artifact. Once the upload is complete, the
file should be moved to the artifact cache.
"""

from pathlib import Path

from wandb import env
from wandb.sdk.lib.filesystem import mkdir_exists_ok
from wandb.sdk.lib.paths import FilePathStr


def get_staging_dir() -> FilePathStr:
    path = Path(env.get_data_dir()) / "artifacts" / "staging"
    try:
        mkdir_exists_ok(path)
    except OSError as e:
        raise PermissionError(
            f"Unable to write staging files to {path!s}. To fix this problem, please set "
            f"{env.DATA_DIR} to a directory where you have the necessary write access."
        ) from e

    full_path = Path(path).expanduser().absolute()
    return FilePathStr(str(full_path))
