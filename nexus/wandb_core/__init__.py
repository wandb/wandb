"""W&B Nexus: Calcium-Rich Bones for the SDK."""
__all__ = ("__version__", "get_nexus_path")

from pathlib import Path

__version__ = "0.17.0b2"


def get_nexus_path() -> Path:
    return (Path(__file__).parent / "wandb-nexus").resolve()
