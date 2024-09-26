from __future__ import annotations

from typing import Container, Union

from pydantic import Discriminator, Field, Tag
from pydantic._internal import _repr
from typing_extensions import Annotated

from wandb.sdk.automations._ops.base import Op
from wandb.sdk.automations._ops.utils import get_op_discriminator_value

#: Placeholder - TODO: make these variadic depending on compared field/expression
# ValueT = TypeVar("ValueT", str, int, float)
ValueT = Union[str, int, float]

EQ = "$eq"
NE = "$ne"
GTE = "$gte"
LT = "$lt"
GT = "$gt"
LTE = "$lte"
CONTAINS = "$contains"  # Note: This isn't actually supported by MongoDB but the backend handles it

IN = "$in"
NIN = "$nin"


class CompareToScalarOp(Op[ValueT]):
    val: ValueT

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.val  # Display as positional args


class Lt(CompareToScalarOp):
    val: ValueT = Field(alias=LT)


class Gt(CompareToScalarOp):
    val: ValueT = Field(alias=GT)


class Lte(CompareToScalarOp):
    val: ValueT = Field(alias=LTE)


class Gte(CompareToScalarOp):
    val: ValueT = Field(alias=GTE)


class Eq(CompareToScalarOp):
    val: ValueT = Field(alias=EQ)


class Ne(CompareToScalarOp):
    val: ValueT = Field(alias=NE)


class Contains(CompareToScalarOp):
    val: ValueT = Field(alias=CONTAINS)


class CompareToContainerOp(Op[Container[ValueT]]):
    vals: list[ValueT]

    def __repr_args__(self) -> _repr.ReprArgs:
        yield from ((None, v) for v in self.vals)


class In(CompareToContainerOp):
    vals: list[ValueT] = Field(alias=IN)


class Nin(CompareToContainerOp):
    vals: list[ValueT] = Field(alias=NIN)


# ------------------------------------------------------------------------------
AnyComparisonOp = Annotated[
    Union[
        Annotated[Lt, Tag(LT)],
        Annotated[Gt, Tag(GT)],
        Annotated[Lte, Tag(LTE)],
        Annotated[Gte, Tag(GTE)],
        Annotated[Eq, Tag(EQ)],
        Annotated[Ne, Tag(NE)],
        Annotated[Contains, Tag(CONTAINS)],
        # ------------------------------------------------------------------------------
        Annotated[In, Tag(IN)],
        Annotated[Nin, Tag(NIN)],
    ],
    Discriminator(get_op_discriminator_value),
]
