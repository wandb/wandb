"""Types that represent operators in MongoDB filter expressions."""

from __future__ import annotations

import sys
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Iterable,
    Tuple,
    TypeVar,
    Union,
    cast,
    overload,
)

from pydantic import BaseModel, ConfigDict, Field
from pydantic.main import IncEx

if TYPE_CHECKING:
    from typing_extensions import TypeAlias

    from wandb.sdk.automations.events import MetricFilter, RunMetricFilter

if sys.version_info >= (3, 12):
    from typing import Literal, override
else:
    from typing_extensions import Literal, override


ScalarTypes = (str, int, float, bool)  # For isinstance() checks
Scalar = Union[str, int, float, bool]  # For type annotations and/or narrowing

# See: https://rich.readthedocs.io/en/stable/pretty.html#rich-repr-protocol
RichReprResult: TypeAlias = Iterable[
    Union[
        Any,
        Tuple[Any],
        Tuple[str, Any],
        Tuple[str, Any, Any],
    ]
]


def op_key(cls: type[OpDict[Any]]) -> str:
    """The dict key for the parsed MongoDB operator."""
    return cast(str, cls.model_fields["inner"].alias)


T = TypeVar("T")
InnerT = TypeVar("InnerT")
TupleOf: TypeAlias = tuple[T, ...]


class OpDict(BaseModel, Generic[InnerT]):
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

    inner: InnerT

    def __repr__(self) -> str:
        # Display operand as a positional arg
        return f"{type(self).__name__}({self.inner!r})"

    def __rich_repr__(self) -> RichReprResult:  # type: ignore[override]
        # https://rich.readthedocs.io/en/stable/pretty.html
        yield (None, self.inner, self.model_fields["inner"].default)

    @override
    def model_dump(
        self,
        *,
        mode: Literal["json", "python"] | str = "json",  # NOTE: changed default
        include: IncEx | None = None,
        exclude: IncEx | None = None,
        context: dict[str, Any] | None = None,
        by_alias: bool = True,  # NOTE: changed default
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        round_trip: bool = True,  # NOTE: changed default
        warnings: bool | Literal["none", "warn", "error"] = True,
        serialize_as_any: bool = False,
    ) -> dict[str, Any]:
        return super().model_dump(
            mode=mode,
            include=include,
            exclude=exclude,
            context=context,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            round_trip=round_trip,
            warnings=warnings,
            serialize_as_any=serialize_as_any,
        )

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


class And(OpDict[TupleOf[Any]]):
    inner: TupleOf[Any] = Field(default=(), alias="$and")


class Or(OpDict[TupleOf[Any]]):
    inner: TupleOf[Any] = Field(default=(), alias="$or")


class Nor(OpDict[TupleOf[Any]]):
    inner: TupleOf[Any] = Field(default=(), alias="$nor")


class Not(OpDict[Any]):
    inner: Any = Field(alias="$not")


# Comparison operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/lt/
# https://www.mongodb.com/docs/manual/reference/operator/query/gt/
# https://www.mongodb.com/docs/manual/reference/operator/query/lte/
# https://www.mongodb.com/docs/manual/reference/operator/query/gte/
# https://www.mongodb.com/docs/manual/reference/operator/query/eq/
# https://www.mongodb.com/docs/manual/reference/operator/query/ne/
# https://www.mongodb.com/docs/manual/reference/operator/query/in/
# https://www.mongodb.com/docs/manual/reference/operator/query/nin/


class Lt(OpDict[Scalar]):
    inner: Scalar = Field(alias="$lt")


class Gt(OpDict[Scalar]):
    inner: Scalar = Field(alias="$gt")


class Lte(OpDict[Scalar]):
    inner: Scalar = Field(alias="$lte")


class Gte(OpDict[Scalar]):
    inner: Scalar = Field(alias="$gte")


class Eq(OpDict[Scalar]):
    inner: Scalar = Field(alias="$eq")


class Ne(OpDict[Scalar]):
    inner: Scalar = Field(alias="$ne")


class In(OpDict[TupleOf[Scalar]]):
    inner: TupleOf[Scalar] = Field(default=(), alias="$in")


class NotIn(OpDict[TupleOf[Scalar]]):
    inner: TupleOf[Scalar] = Field(default=(), alias="$nin")


# Element operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/exists/


class Exists(OpDict[bool]):
    inner: bool = Field(alias="$exists")


# Evaluation operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/regex/
#
# Note: "$contains" is NOT a formal MongoDB operator, but the backend recognizes and
# executes it as a substring-match filter.


class Regex(OpDict[str]):
    inner: str = Field(alias="$regex")  #: The regex expression to match against.


class Contains(OpDict[str]):
    inner: str = Field(alias="$contains")  #: The substring to match against.
