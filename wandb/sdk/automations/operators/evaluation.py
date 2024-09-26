from __future__ import annotations

from typing import Union

from pydantic import Discriminator, Field, Tag
from pydantic._internal import _repr
from typing_extensions import Annotated

from wandb.sdk.automations.operators.base_op import Op
from wandb.sdk.automations.operators.utils import get_op_discriminator_value

REGEX = "$regex"
EXPR = "$expr"
OPTIONS = "$options"


class EvalOp(Op):
    pass


class Regex(EvalOp):
    regex: str = Field(alias=REGEX)
    options: str | None = Field(None, alias=OPTIONS)

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.regex


class Expr(EvalOp):
    exprs: str = Field(alias=EXPR)

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.exprs


AnyEvaluationOp = Annotated[
    Union[
        Annotated[Regex, Tag(REGEX)],
        Annotated[Expr, Tag(EXPR)],
    ],
    Discriminator(get_op_discriminator_value),
]
