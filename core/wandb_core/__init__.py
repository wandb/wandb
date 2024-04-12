"""W&B Core: This is the backend for the W&B client library."""

__all__ = (
    "__version__",
    "get_core_path",
    "get_nexus_path",
)

from pathlib import Path

__version__ = "0.17.0b11"


_cached_core_path = None


def get_core_path() -> str:
    global _cached_core_path

    if _cached_core_path is None:
        path = (Path(__file__).parent / "wandb-core").resolve()

        # If the binary doesn't exist, we return an empty string.
        if path.exists():
            _cached_core_path = str(path)
        else:
            _cached_core_path = ""

    return _cached_core_path


# for backwards compatibility
def get_nexus_path() -> str:
    return get_core_path()
