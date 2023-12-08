"""W&B Core: This is the backend for the W&B client library."""
__all__ = ("__version__", "get_core_path")

from pathlib import Path

__version__ = "0.17.0b2"


def get_core_path() -> Path:
    return (Path(__file__).parent / "wandb-core").resolve()
