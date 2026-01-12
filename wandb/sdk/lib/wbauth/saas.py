from __future__ import annotations

from urllib.parse import urlsplit


def is_wandb_domain(url: str) -> bool:
    """Returns whether the URL points to an official W&B server."""
    _, netloc, _, _, _ = urlsplit(url)
    return netloc.endswith("wandb.ai")
