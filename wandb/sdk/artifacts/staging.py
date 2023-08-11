from pathlib import Path
from typing import Optional

from wandb import env
from wandb.errors import term
from wandb.sdk.lib.filesystem import mkdir_exists_ok
from wandb.sdk.lib.paths import StrPath

_staging_dir: Optional[Path] = None


def get_staging_dir() -> Path:
    """Return the staging directory for artifact files."""
    global _staging_dir
    if _staging_dir is None:
        path = Path(env.get_data_dir()) / "artifacts" / "staging"
        _staging_dir = path.expanduser().resolve()
    try:
        mkdir_exists_ok(_staging_dir)
    except OSError as e:
        raise PermissionError(
            f"Unable to write staging files to {_staging_dir}. To fix this problem "
            f"please set {env.DATA_DIR} to a directory where you have write access."
        ) from e
    return _staging_dir


def is_staged_copy(local_path: StrPath) -> bool:
    """Returns True if the given path is a staging copy of a local file."""
    local_path = Path(local_path).expanduser().resolve()
    try:
        # Raises if the path is not a child of the staging directory.
        local_path.relative_to(get_staging_dir())
        return local_path.is_file()
    except ValueError:
        return False


def remove_from_staging(local_path: StrPath) -> None:
    """Remove the given file from staging."""
    local_path = Path(local_path)
    if not is_staged_copy(local_path):
        term.termerror(f"Staging file '{local_path}' is not in staging directory")
        return
    try:
        local_path.chmod(0o600)
        local_path.unlink()
    except PermissionError:
        term.termerror(f"Unable to remove staging file {local_path}")
    except FileNotFoundError:
        pass
