"""Types for parsing, serializing, and defining MongoDB-compatible operators for filter/query expressions.

https://www.mongodb.com/docs/manual/reference/operator/query/
"""

from __future__ import annotations

from typing import Any, ClassVar, Union

from pydantic import ConfigDict, model_serializer, model_validator
from pydantic._internal import _repr
from pydantic_core import to_jsonable_python

from wandb.sdk.automations._base import Base

Scalar = Union[str, int, float, bool]


class OpDict(Base):
    """Base class for MongoDB query operators."""

    model_config = ConfigDict(
        alias_generator=None,  # Use field names as-is
        frozen=True,  # Make pseudo-immutable for easier comparison and hashing, as needed
    )

    OP: ClassVar[str]

    other: Any

    def __repr_args__(self) -> _repr.ReprArgs:
        # Display set field values as positional args
        for field, value in self:
            if field in self.model_fields_set:
                yield None, value

    @model_validator(mode="before")
    @classmethod
    def from_dict(cls, data: Any) -> Any:
        """Parse from a MongoDB dict representation of the operator."""
        # If needed, convert e.g. `{"$gt": 123}` -> `{"other": 123}` before instantiation
        if isinstance(data, dict) and data.keys() == {cls.OP}:
            return cls(other=data[cls.OP])
        return data

    @model_serializer(mode="plain")
    def to_dict(self) -> dict[str, Any]:
        """Return a MongoDB dict representation of the operator."""
        return {
            to_jsonable_python(self.OP): to_jsonable_python(
                self.other, serialize_as_any=True
            )
        }

    # Default implementations for logical python operators e.g. `a | b`, `a & b`, `~a`
    def __or__(self, other: Any) -> Or:
        return Or(other=[self, other])

    def __and__(self, other: Any) -> And:
        return And(other=[self, other])

    def __invert__(self) -> Not:
        return Not(other=self)


# ------------------------------------------------------------------------------
# Variadic logical operator(s)


# https://www.mongodb.com/docs/manual/reference/operator/query/and/
class And(OpDict):
    """Parsed `$and` operator."""

    OP: ClassVar[str] = "$and"
    other: tuple[Any, ...] = ()


# https://www.mongodb.com/docs/manual/reference/operator/query/or/
class Or(OpDict):
    """Parsed `$or` operator."""

    OP: ClassVar[str] = "$or"
    other: tuple[Any, ...] = ()


# https://www.mongodb.com/docs/manual/reference/operator/query/nor/
class Nor(OpDict):
    """Parsed `$nor` operator."""

    OP: ClassVar[str] = "$nor"
    other: tuple[Any, ...] = ()


# ------------------------------------------------------------------------------
# Unary logical operator(s)


# https://www.mongodb.com/docs/manual/reference/operator/query/not/
class Not(OpDict):
    """Parsed `$not` operator."""

    OP: ClassVar[str] = "$not"
    other: Any


# ------------------------------------------------------------------------------
# Comparison operator(s)


# https://www.mongodb.com/docs/manual/reference/operator/query/lt/
class Lt(OpDict):
    """Parsed `$lt` operator."""

    OP: ClassVar[str] = "$lt"
    other: Scalar


# https://www.mongodb.com/docs/manual/reference/operator/query/gt/
class Gt(OpDict):
    """Parsed `$gt` operator."""

    OP: ClassVar[str] = "$gt"
    other: Scalar


# https://www.mongodb.com/docs/manual/reference/operator/query/lte/
class Lte(OpDict):
    """Parsed `$lte` operator."""

    OP: ClassVar[str] = "$lte"
    other: Scalar


# https://www.mongodb.com/docs/manual/reference/operator/query/gte/
class Gte(OpDict):
    """Parsed `$gte` operator."""

    OP: ClassVar[str] = "$gte"
    other: Scalar


# https://www.mongodb.com/docs/manual/reference/operator/query/eq/
class Eq(OpDict):
    """Parsed `$eq` operator."""

    OP: ClassVar[str] = "$eq"
    other: Scalar


# https://www.mongodb.com/docs/manual/reference/operator/query/ne/
class Ne(OpDict):
    """Parsed `$ne` operator."""

    OP: ClassVar[str] = "$ne"
    other: Scalar


# https://www.mongodb.com/docs/manual/reference/operator/query/in/
class In(OpDict):
    """Parsed `$in` operator."""

    OP: ClassVar[str] = "$in"
    other: tuple[Scalar, ...]


# https://www.mongodb.com/docs/manual/reference/operator/query/nin/
class NotIn(OpDict):
    """Parsed `$nin` operator."""

    OP: ClassVar[str] = "$nin"
    other: tuple[Scalar, ...]


# ------------------------------------------------------------------------------
# Evaluation operator(s)


# https://www.mongodb.com/docs/manual/reference/operator/query/regex/
class Regex(OpDict):
    """Parsed `$regex` operator."""

    OP: ClassVar[str] = "$regex"
    other: str  #: The regex expression to match against.


# Note: This is NOT a formal MongoDB operator, but the backend recognizes and
# executes it as a substring-match filter.
class Contains(OpDict):
    """Parsed `$contains` operator."""

    OP: ClassVar[str] = "$contains"
    other: str  #: The substring to match against.
