from __future__ import annotations

from typing import Any

from wandb.sdk.automations._filters.base import Op


def get_op_tag(obj: dict[str, Any] | Op) -> str | None:
    """Return the discriminator value to identify the Op type in a tagged union."""
    if isinstance(obj, dict):
        return next((key for key in obj.keys() if key.startswith("$")), None)

    if isinstance(obj, Op):
        return obj.op

    return None
