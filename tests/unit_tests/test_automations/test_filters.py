from __future__ import annotations

from string import printable

from hypothesis import given
from hypothesis.strategies import lists, text
from wandb.sdk.automations import filters as flt

from ._strategies import expr_dicts, scalars


# Variadic logical ops
@given(lists(expr_dicts()))
def test_and(args):
    op = flt.and_(*args)
    assert isinstance(op, flt.And)

    # Should still behave as a pydantic model and be round-trippable
    dct = op.model_dump()
    assert dct == {"$and": list(args)}
    assert flt.And.model_validate(dct) == op


@given(lists(expr_dicts()))
def test_or(args):
    op = flt.or_(*args)
    assert isinstance(op, flt.Or)

    # Should still behave as a pydantic model and be round-trippable
    dct = op.model_dump()
    assert dct == {"$or": list(args)}
    assert flt.Or.model_validate(dct) == op


@given(lists(expr_dicts()))
def test_nor(args):
    op = flt.nor_(*args)
    assert isinstance(op, flt.Nor)

    dct = op.model_dump()
    # Should still behave as a pydantic model and be round-trippable
    assert dct == {"$nor": list(args)}
    assert flt.Nor.model_validate(dct) == op


# Unary logical ops
@given(expr_dicts())
def test_not(arg):
    op = flt.not_(arg)
    assert isinstance(op, flt.Not)

    dct = op.model_dump()
    # Should still behave as a pydantic model and be round-trippable
    assert dct == {"$not": arg}
    assert flt.Not.model_validate(dct) == op


# Comparison ops
@given(scalars)
def test_gt(arg):
    op = flt.gt(arg)
    assert isinstance(op, flt.Gt)

    dct = op.model_dump()
    # Should still behave as a pydantic model and be round-trippable
    assert dct == {"$gt": arg}
    assert flt.Gt.model_validate(dct) == op


@given(scalars)
def test_lt(arg):
    op = flt.lt(arg)
    assert isinstance(op, flt.Lt)

    dct = op.model_dump()
    # Should still behave as a pydantic model and be round-trippable
    assert dct == {"$lt": arg}
    assert flt.Lt.model_validate(dct) == op


@given(scalars)
def test_gte(arg):
    op = flt.gte(arg)
    assert isinstance(op, flt.Gte)

    dct = op.model_dump()
    # Should still behave as a pydantic model and be round-trippable
    assert dct == {"$gte": arg}
    assert flt.Gte.model_validate(dct) == op


@given(scalars)
def test_lte(arg):
    op = flt.lte(arg)
    assert isinstance(op, flt.Lte)

    dct = op.model_dump()
    # Should still behave as a pydantic model and be round-trippable
    assert dct == {"$lte": arg}
    assert flt.Lte.model_validate(dct) == op


@given(scalars)
def test_eq(arg):
    op = flt.eq(arg)
    assert isinstance(op, flt.Eq)

    dct = op.model_dump()
    # Should still behave as a pydantic model and be round-trippable
    assert dct == {"$eq": arg}
    assert flt.Eq.model_validate(dct) == op


@given(scalars)
def test_ne(arg):
    op = flt.ne(arg)
    assert isinstance(op, flt.Ne)

    dct = op.model_dump()
    # Should still behave as a pydantic model and be round-trippable
    assert dct == {"$ne": arg}
    assert flt.Ne.model_validate(dct) == op


@given(lists(scalars))
def test_in(arg):
    op = flt.in_(arg)
    assert isinstance(op, flt.In)

    dct = op.model_dump()
    # Should still behave as a pydantic model and be round-trippable
    assert dct == {"$in": arg}
    assert flt.In.model_validate(dct) == op


@given(lists(scalars))
def test_not_in(arg):
    op = flt.not_in(arg)
    assert isinstance(op, flt.NotIn)

    dct = op.model_dump()
    # Should still behave as a pydantic model and be round-trippable
    assert dct == {"$nin": arg}
    assert flt.NotIn.model_validate(dct) == op


# Evaluation ops
@given(text(printable))  # TODO: Generate valid regex expressions
def test_regex(arg):
    op = flt.regex_match(arg)
    assert isinstance(op, flt.Regex)

    dct = op.model_dump()
    # Should still behave as a pydantic model and be round-trippable
    assert dct == {"$regex": arg}
    assert flt.Regex.model_validate(dct) == op


@given(text(printable))
def test_contains(arg):
    op = flt.contains(arg)
    assert isinstance(op, flt.Contains)

    dct = op.model_dump()
    # Should still behave as a pydantic model and be round-trippable
    assert dct == {"$contains": arg}
    assert flt.Contains.model_validate(dct) == op
