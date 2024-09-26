from __future__ import annotations

from typing import TYPE_CHECKING, Collection, Iterable, Iterator, Union

from pydantic import Discriminator, Field, Tag, field_validator
from pydantic._internal import _repr
from typing_extensions import Annotated

from wandb.sdk.automations.operators.base_op import Op
from wandb.sdk.automations.operators.utils import get_op_discriminator_value

if TYPE_CHECKING:
    from wandb.sdk.automations.operators.op import AnyExpr


NOT = "$not"

AND = "$and"
OR = "$or"
NOR = "$nor"


# MongoDB specs: https://www.mongodb.com/docs/manual/reference/operator/query-logical/
# ------------------------------------------------------------------------------
class LogicalVariadicOp(Op):  # TODO: parameterize this generic w/o circular imports
    """A logical operator that operates on any number of operands."""

    exprs: Collection[AnyExpr]

    def __repr_args__(self) -> _repr.ReprArgs:
        # Represent the inner expression(s) as positional args
        yield from ((None, expr) for expr in self.exprs)


def _flatten_nested_ops(cls: type[And | Or], exprs: Iterable[AnyExpr]) -> list[AnyExpr]:
    def _iter_flattened() -> Iterator[AnyExpr]:
        for x in exprs:
            if isinstance(x, cls):
                yield from x.exprs
            else:
                yield x

    return list(_iter_flattened())


class And(LogicalVariadicOp):
    """Parsed `$and` operator, which may also be interpreted as an "all_of" operator."""

    exprs: list[AnyExpr] = Field(alias=AND)

    _flatten = field_validator("exprs", mode="after")(_flatten_nested_ops)


class Or(LogicalVariadicOp):
    """Parsed `$or` operator, which may also be interpreted as an "any_of" operator."""

    exprs: list[AnyExpr] = Field(alias=OR)

    _flatten = field_validator("exprs", mode="after")(_flatten_nested_ops)


class Nor(LogicalVariadicOp):
    exprs: list[AnyExpr] = Field(alias=NOR)


# ------------------------------------------------------------------------------
class LogicalUnaryOp(Op):  # TODO: parameterize this generic w/o circular imports
    expr: AnyExpr

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.expr  # Display as positional args

    # TODO: Figure out where to add validation/flattening logic for
    #   - not not expr -> expr
    #   - not in values -> nin values
    #   - not nin values -> in values
    #   - not nor exprs -> any exprs


class Not(LogicalUnaryOp):
    expr: AnyExpr = Field(alias=NOT)


# ------------------------------------------------------------------------------
AnyLogicalOp = Annotated[
    Union[
        Annotated[And, Tag(AND)],
        Annotated[Or, Tag(OR)],
        Annotated[Nor, Tag(NOR)],
        Annotated[Not, Tag(NOT)],
    ],
    Discriminator(get_op_discriminator_value),
]
