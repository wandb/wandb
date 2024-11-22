from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from pydantic import model_serializer, model_validator
from pydantic._internal import _repr

from wandb.sdk.automations._base import Base

if TYPE_CHECKING:
    from .logic import And, Not, Or


class Op(Base):
    """Base class for operators in expressions."""

    op: ClassVar[str]

    inner_operand: Any

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.inner_operand  # Display as positional args

    @model_serializer
    def _to_mongodb_dict(self) -> dict[str, Any]:
        return {self.op: self.inner_operand}

    @model_validator(mode="before")
    @classmethod
    def _from_mongodb_dict(cls, data: dict[str, Any]) -> Any:
        if data and isinstance(data, dict) and ("inner_operand" not in data.keys()):
            return {"inner_operand": next(iter(data.values()))}
        return data

    def __or__(self, other: OpT) -> Or:
        from wandb.sdk.automations._filters.logic import Or

        return Or(inner_operand=[self, other])

    def __and__(self, other: OpT) -> And:
        from wandb.sdk.automations._filters.logic import And

        return And(inner_operand=[self, other])

    def __invert__(self) -> Not:
        from wandb.sdk.automations._filters.logic import Not

        return Not(inner_operand=self)


OpT = TypeVar("OpT", bound=Op)
