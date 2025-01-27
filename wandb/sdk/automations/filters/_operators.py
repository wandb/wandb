"""Types for parsing, serializing, and defining MongoDB-compatible operators for filter/query expressions.

https://www.mongodb.com/docs/manual/reference/operator/query/
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Mapping, Union, overload

from pydantic import BaseModel, ConfigDict, model_serializer, model_validator
from pydantic._internal import _repr
from pydantic_core import to_jsonable_python

if TYPE_CHECKING:
    from wandb.sdk.automations.events import MetricFilter, RunMetricFilter

Scalar = Union[str, int, float, bool]


class OpDict(BaseModel):
    """Parsed MongoDB operator dict."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        validate_default=True,
        extra="forbid",
        use_attribute_docstrings=True,
        from_attributes=True,
        revalidate_instances="always",
        frozen=True,  # Make pseudo-immutable for easier comparison and hashing, as needed
    )

    OP: ClassVar[str]

    inner: Any

    def __repr_args__(self) -> _repr.ReprArgs:
        # Display operand as a positional arg
        yield None, self.inner

    @model_validator(mode="before")
    @classmethod
    def _validate(cls, data: Any) -> Any:
        """Parse from a MongoDB dict representation of the operator."""
        # If needed, convert e.g. `{"$gt": 123}` -> `{"inner": 123}` before instantiation
        if isinstance(data, Mapping) and (cls.OP in data):
            return cls(inner=data[cls.OP])
        return data

    @model_serializer(mode="plain")
    def _serialize(self) -> dict[str, Any]:
        """Return a MongoDB dict representation of the operator."""
        return {self.OP: to_jsonable_python(self.inner, serialize_as_any=True)}

    # Default implementations for logical python operators e.g. `a | b`, `a & b`, `~a`
    def __or__(self, other: Any) -> Or:
        return Or(inner=[self, other])

    @overload
    def __and__(self, other: MetricFilter) -> RunMetricFilter: ...
    @overload
    def __and__(self, other: Any) -> And: ...

    def __and__(self, other: Any) -> And | RunMetricFilter:
        from wandb.sdk.automations.events import MetricFilter

        # Special handling `run_filter & metric_filter`
        if isinstance(other, MetricFilter):
            return other.__and__(self)
        return And(inner=[self, other])

    def __invert__(self) -> Not:
        return Not(inner=self)


# Logical operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/and/
# https://www.mongodb.com/docs/manual/reference/operator/query/or/
# https://www.mongodb.com/docs/manual/reference/operator/query/nor/
# https://www.mongodb.com/docs/manual/reference/operator/query/not/


class And(OpDict):
    OP: ClassVar[str] = "$and"
    inner: tuple[Any, ...] = ()


class Or(OpDict):
    OP: ClassVar[str] = "$or"
    inner: tuple[Any, ...] = ()


class Nor(OpDict):
    OP: ClassVar[str] = "$nor"
    inner: tuple[Any, ...] = ()


class Not(OpDict):
    OP: ClassVar[str] = "$not"
    inner: Any


# Comparison operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/lt/
# https://www.mongodb.com/docs/manual/reference/operator/query/gt/
# https://www.mongodb.com/docs/manual/reference/operator/query/lte/
# https://www.mongodb.com/docs/manual/reference/operator/query/gte/
# https://www.mongodb.com/docs/manual/reference/operator/query/eq/
# https://www.mongodb.com/docs/manual/reference/operator/query/ne/
# https://www.mongodb.com/docs/manual/reference/operator/query/in/
# https://www.mongodb.com/docs/manual/reference/operator/query/nin/


class Lt(OpDict):
    OP: ClassVar[str] = "$lt"
    inner: Scalar


class Gt(OpDict):
    OP: ClassVar[str] = "$gt"
    inner: Scalar


class Lte(OpDict):
    OP: ClassVar[str] = "$lte"
    inner: Scalar


class Gte(OpDict):
    OP: ClassVar[str] = "$gte"
    inner: Scalar


class Eq(OpDict):
    OP: ClassVar[str] = "$eq"
    inner: Scalar


class Ne(OpDict):
    OP: ClassVar[str] = "$ne"
    inner: Scalar


class In(OpDict):
    OP: ClassVar[str] = "$in"
    inner: tuple[Scalar, ...]


class NotIn(OpDict):
    OP: ClassVar[str] = "$nin"
    inner: tuple[Scalar, ...]


# Element operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/exists/


class Exists(OpDict):
    OP: ClassVar[str] = "$exists"
    inner: bool


# Evaluation operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/regex/
#
# Note: "$contains" is NOT a formal MongoDB operator, but the backend recognizes and
# executes it as a substring-match filter.


class Regex(OpDict):
    OP: ClassVar[str] = "$regex"
    inner: str  #: The regex expression to match against.


class Contains(OpDict):
    OP: ClassVar[str] = "$contains"
    inner: str  #: The substring to match against.
