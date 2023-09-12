"""nexus."""

from pathlib import Path


def get_nexus_path() -> Path:
    return (Path(__file__).parent / "wandb-nexus").resolve()
