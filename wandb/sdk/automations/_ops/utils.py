from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from typing_extensions import Unpack

    from wandb.sdk.automations._ops.base import Op, OperandsT


def get_op_discriminator_value(
    obj: dict[str, Any] | Op[Unpack[OperandsT]],
) -> str | None:
    from wandb.sdk.automations._ops.base import Op

    if isinstance(obj, dict):
        key = next(k for k in obj.keys() if k.startswith("$"))
        return cast(str, key)

    if isinstance(obj, Op):
        field_info = next(iter(obj.model_fields.values()))
        return cast(str, field_info.alias)

    return None
