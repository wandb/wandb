from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import ConfigDict, model_serializer, model_validator
from pydantic._internal import _repr
from pydantic_core.core_schema import SerializerFunctionWrapHandler

from wandb.sdk.automations._base import Base

if TYPE_CHECKING:
    from .filter_expr import AnyExpr
    from .filter_ops import And, Not, Or


class Op(Base):
    """Base class for MongoDB query operator expressions."""

    model_config = ConfigDict(
        alias_generator=None,  # Use field names as-is
        frozen=True,  # Make pseudo-immutable for easier comparison and hashing, as needed
    )

    OP: ClassVar[str]

    other: Any

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.other  # Display as positional args

    @model_serializer(mode="wrap")
    def _to_dict(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Return a dict representation of the operator."""
        # Wrap serialization handler needed to avoid error on `obj.model_dump()`:
        #   TypeError: 'MockValSer' object cannot be converted to 'SchemaSerializer'
        # General info:
        # https://docs.pydantic.dev/latest/api/functional_serializers/#pydantic.functional_serializers.model_serializer
        dct = handler(self)
        return {self.OP: dct["other"]}

    @model_validator(mode="before")
    @classmethod
    def from_dict(cls, data: Any) -> Any:
        """Parse from a dict representation of the operator."""
        # If needed, convert e.g. `{"$gt": 123}` -> `{"other": 123}` before instantiation
        if isinstance(data, dict) and data.keys() == {cls.OP}:
            return {"other": data[cls.OP]}
        return data

    def __or__(self, other: AnyExpr) -> Or:
        from wandb.sdk.automations._filters.filter_ops import Or

        return Or(other=[self, other])

    def __and__(self, other: AnyExpr) -> And:
        from wandb.sdk.automations._filters.filter_ops import And

        return And(other=[self, other])

    def __invert__(self) -> Not:
        from wandb.sdk.automations._filters.filter_ops import Not

        return Not(other=self)
