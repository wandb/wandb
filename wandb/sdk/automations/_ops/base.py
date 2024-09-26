from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from typing_extensions import Generic, TypeVarTuple, Unpack  # noqa: UP035

from wandb.sdk.automations._base import Base

if TYPE_CHECKING:
    from wandb.sdk.automations._ops.logic import And, Or


FieldT = TypeVar("FieldT")  #: Represents the data type on the field being compared
OperandsT = TypeVarTuple("OperandsT")  #: Variadic typevar for parameterizing ops


class Op(Base, Generic[Unpack[OperandsT]]):
    """Base class for operators in expressions."""

    def __or__(self, other: OpT) -> Or:
        from wandb.sdk.automations._ops.logic import Or

        return Or(exprs=[self, other])

    def __and__(self, other: OpT) -> And:
        from wandb.sdk.automations._ops.logic import And

        return And(exprs=[self, other])

    def __invert__(self) -> Op:
        from wandb.sdk.automations._ops.logic import Not

        return Not(expr=self)


OpT = TypeVar("OpT", bound=Op)
