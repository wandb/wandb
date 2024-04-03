"""W&B Core: This is the backend for the W&B client library."""

from pathlib import Path

from .version import __version__

__all__ = (
    "__version__",
    "get_core_path",
    "get_nexus_path",
)


def get_core_path() -> Path:
    return (Path(__file__).parent / "wandb-core").resolve()


# for backwards compatibility
def get_nexus_path() -> Path:
    return get_core_path()
