from pathlib import Path
from typing import Optional

from wandb import env
from wandb.sdk.lib.filesystem import mkdir_exists_ok

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
