from __future__ import annotations

from string import printable

from hypothesis import given
from hypothesis.strategies import lists, text
from wandb.sdk.automations.filters import (
    And,
    Contains,
    Eq,
    Gt,
    Gte,
    In,
    Lt,
    Lte,
    Ne,
    Nor,
    Not,
    NotIn,
    Or,
    Regex,
    and_,
    contains,
    eq,
    gt,
    gte,
    in_,
    lt,
    lte,
    ne,
    nor_,
    not_,
    not_in,
    or_,
    regex_match,
)

from ._strategies import expr_dicts, scalars


# Variadic logical ops
@given(lists(expr_dicts()))
def test_and(args):
    op = and_(*args)
    op_dict = op.model_dump()
    assert op_dict == {"$and": list(args)}
    assert And.model_validate(op_dict) == op


@given(lists(expr_dicts()))
def test_or(args):
    op = or_(*args)
    op_dict = op.model_dump()
    assert op_dict == {"$or": list(args)}
    assert Or.model_validate(op_dict) == op


@given(lists(expr_dicts()))
def test_nor(args):
    op = nor_(*args)
    op_dict = op.model_dump()
    assert op_dict == {"$nor": list(args)}
    assert Nor.model_validate(op_dict) == op


# Unary logical ops
@given(expr_dicts())
def test_not(arg):
    op = not_(arg)
    op_dict = op.model_dump()
    assert op_dict == {"$not": arg}
    assert Not.model_validate(op_dict) == op


# Comparison ops
@given(scalars)
def test_gt(arg):
    op = gt(arg)
    op_dict = op.model_dump()
    assert op_dict == {"$gt": arg}
    assert Gt.model_validate(op_dict) == op


@given(scalars)
def test_lt(arg):
    op = lt(arg)
    op_dict = op.model_dump()
    assert op_dict == {"$lt": arg}
    assert Lt.model_validate(op_dict) == op


@given(scalars)
def test_gte(arg):
    op = gte(arg)
    op_dict = op.model_dump()
    assert op_dict == {"$gte": arg}
    assert Gte.model_validate(op_dict) == op


@given(scalars)
def test_lte(arg):
    op = lte(arg)
    op_dict = op.model_dump()
    assert op_dict == {"$lte": arg}
    assert Lte.model_validate(op_dict) == op


@given(scalars)
def test_eq(arg):
    op = eq(arg)
    op_dict = op.model_dump()
    assert op_dict == {"$eq": arg}
    assert Eq.model_validate(op_dict) == op


@given(scalars)
def test_ne(arg):
    op = ne(arg)
    op_dict = op.model_dump()
    assert op_dict == {"$ne": arg}
    assert Ne.model_validate(op_dict) == op


@given(lists(scalars))
def test_in(arg):
    op = in_(arg)
    op_dict = op.model_dump()
    assert op_dict == {"$in": arg}
    assert In.model_validate(op_dict) == op


@given(lists(scalars))
def test_not_in(arg):
    op = not_in(arg)
    op_dict = op.model_dump()
    assert op_dict == {"$nin": arg}
    assert NotIn.model_validate(op_dict) == op


# Evaluation ops
@given(text(printable))  # TODO: Generate valid regex expressions
def test_regex(arg):
    op = regex_match(arg)
    op_dict = op.model_dump()
    assert op_dict == {"$regex": arg}
    assert Regex.model_validate(op_dict) == op


@given(text(printable))
def test_contains(arg):
    op = contains(arg)
    op_dict = op.model_dump()
    assert op_dict == {"$contains": arg}
    assert Contains.model_validate(op_dict) == op
