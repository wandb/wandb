from __future__ import annotations

from typing import TYPE_CHECKING

from more_itertools import first

if TYPE_CHECKING:
    from wandb.sdk.automations.expr.base import Op


def get_op_discriminator_value(obj: dict | Op) -> str:
    from wandb.sdk.automations.expr.base import Op

    match obj:
        case dict() if len(obj) == 1 and (key := first(obj.keys())).startswith("$"):
            return key
        case Op():
            field_info = first(obj.model_fields.values())
            return field_info.alias
        case _:
            return None
