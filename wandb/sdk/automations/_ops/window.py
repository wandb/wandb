"""See: https://www.mongodb.com/docs/manual/reference/operator/aggregation/#window-operators."""


# TODO: Decide whether we need this

from typing import Any

from wandb.sdk.automations._base import Base
from wandb.sdk.automations._ops.op import AnyExpr, ExpressionField


class Window(Base):
    documents: tuple[str | int, str | int] | None = None
    range: tuple[str | int, str | int] | None = None
    unit: str | None = None


class WindowedOutput(Base):
    window_op: Any
    window_op_params: Any  # E.g. the column name to aggregate
    window: Window


class SetWindowFields(Base):
    partition_by: AnyExpr | None = None
    sort_by: AnyExpr | None = None
    """
    Required for some operations, see: https://www.mongodb.com/docs/manual/reference/operator/aggregation/setWindowFields/#std-label-setWindowFields-restrictions
    """

    output: dict[ExpressionField, WindowedOutput]
