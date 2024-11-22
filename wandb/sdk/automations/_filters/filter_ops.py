"""Types for parsing, serializing, and defining MongoDB-compatible operators for filter/query expressions.

MongoDB specs: https://www.mongodb.com/docs/manual/reference/operator/query-logical/
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Union

from pydantic import ConfigDict, model_serializer, model_validator
from pydantic._internal import _repr
from pydantic_core.core_schema import SerializerFunctionWrapHandler

from wandb.sdk.automations._base import Base

if TYPE_CHECKING:
    from .filter_expr import AnyExpr


Scalar = Union[str, int, float, bool]


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

    # Default implementations for logical python operators e.g. `a | b`, `a & b`, `~a`
    def __or__(self, other: AnyExpr) -> Or:
        from wandb.sdk.automations._filters.filter_ops import Or

        return Or(other=[self, other])

    def __and__(self, other: AnyExpr) -> And:
        from wandb.sdk.automations._filters.filter_ops import And

        return And(other=[self, other])

    def __invert__(self) -> Not:
        from wandb.sdk.automations._filters.filter_ops import Not

        return Not(other=self)


# ------------------------------------------------------------------------------
# Logical operators (variadic)
class And(Op):
    """Parsed `$and` operator, which may also be interpreted as an "all_of" operator."""

    OP: ClassVar[str] = "$and"
    other: tuple[AnyExpr, ...] = ()  # Ok since tuples are immutable


class Or(Op):
    """Parsed `$or` operator, which may also be interpreted as an "any_of" operator."""

    OP: ClassVar[str] = "$or"
    other: tuple[AnyExpr, ...] = ()  # Ok since tuples are immutable


class Nor(Op):
    """Parsed `$nor` operator, which may also be interpreted as a "not_any" operator."""

    OP: ClassVar[str] = "$nor"
    other: tuple[AnyExpr, ...] = ()  # Ok since tuples are immutable


# Logical operators (unary)
class Not(Op):
    """Parsed `$not` operator."""

    OP: ClassVar[str] = "$not"
    other: AnyExpr


# ------------------------------------------------------------------------------
# Comparison operators
class Lt(Op):
    OP: ClassVar[str] = "$lt"
    other: Scalar


class Gt(Op):
    OP: ClassVar[str] = "$gt"
    other: Scalar


class Lte(Op):
    OP: ClassVar[str] = "$lte"
    other: Scalar


class Gte(Op):
    OP: ClassVar[str] = "$gte"
    other: Scalar


class Eq(Op):
    OP: ClassVar[str] = "$eq"
    other: Scalar


class Ne(Op):
    OP: ClassVar[str] = "$ne"
    other: Scalar


class In(Op):
    OP: ClassVar[str] = "$in"
    other: tuple[Scalar, ...]


class NotIn(Op):
    OP: ClassVar[str] = "$nin"
    other: tuple[Scalar, ...]


# ------------------------------------------------------------------------------
# Evaluation operators
class Regex(Op):
    OP: ClassVar[str] = "$regex"
    other: str  #: The regex expression to match against.


class Contains(Op):
    # Not an actual MongoDB operator, but the backend treats this as a substring-match filter.
    OP: ClassVar[str] = "$contains"
    other: str  #: The substring to match against.
