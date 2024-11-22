from __future__ import annotations

from string import printable

from hypothesis import given
from hypothesis.strategies import lists, text
from wandb.sdk.automations import filters

from ._strategies import expr_dicts, scalars

# TODO: Test for lossless round-trip encoding/decoding


# Variadic logical ops
@given(lists(expr_dicts()))
def test_and(args):
    op = filters.and_(*args)
    assert isinstance(op, filters.And)

    filter_dict = op.model_dump()
    assert filter_dict == {"$and": list(args)}
    assert filters.And.model_validate(filter_dict) == op


@given(lists(expr_dicts()))
def test_or(args):
    op = filters.or_(*args)
    assert isinstance(op, filters.Or)

    filter_dict = op.model_dump()
    assert filter_dict == {"$or": list(args)}
    assert filters.Or.model_validate(filter_dict) == op


@given(lists(expr_dicts()))
def test_nor(args):
    op = filters.nor_(*args)
    assert isinstance(op, filters.Nor)

    filter_dict = op.model_dump()
    assert filter_dict == {"$nor": list(args)}
    assert filters.Nor.model_validate(filter_dict) == op


# Unary logical ops
@given(expr_dicts())
def test_not(arg):
    op = filters.not_(arg)
    assert isinstance(op, filters.Not)

    filter_dict = op.model_dump()
    assert filter_dict == {"$not": arg}
    assert filters.Not.model_validate(filter_dict) == op


# Comparison ops
@given(scalars)
def test_gt(arg):
    op = filters.gt(arg)
    assert isinstance(op, filters.Gt)

    filter_dict = op.model_dump()
    assert filter_dict == {"$gt": arg}
    assert filters.Gt.model_validate(filter_dict) == op


@given(scalars)
def test_lt(arg):
    op = filters.lt(arg)
    assert isinstance(op, filters.Lt)

    filter_dict = op.model_dump()
    assert filter_dict == {"$lt": arg}
    assert filters.Lt.model_validate(filter_dict) == op


@given(scalars)
def test_gte(arg):
    op = filters.gte(arg)
    assert isinstance(op, filters.Gte)

    filter_dict = op.model_dump()
    assert filter_dict == {"$gte": arg}
    assert filters.Gte.model_validate(filter_dict) == op


@given(scalars)
def test_lte(arg):
    op = filters.lte(arg)
    assert isinstance(op, filters.Lte)

    filter_dict = op.model_dump()
    assert filter_dict == {"$lte": arg}
    assert filters.Lte.model_validate(filter_dict) == op


@given(scalars)
def test_eq(arg):
    op = filters.eq(arg)
    assert isinstance(op, filters.Eq)

    filter_dict = op.model_dump()
    assert filter_dict == {"$eq": arg}
    assert filters.Eq.model_validate(filter_dict) == op


@given(scalars)
def test_ne(arg):
    op = filters.ne(arg)
    assert isinstance(op, filters.Ne)

    filter_dict = op.model_dump()
    assert filter_dict == {"$ne": arg}
    assert filters.Ne.model_validate(filter_dict) == op


@given(lists(scalars))
def test_in(arg):
    op = filters.in_(arg)
    assert isinstance(op, filters.In)

    filter_dict = op.model_dump()
    assert filter_dict == {"$in": arg}
    assert filters.In.model_validate(filter_dict) == op


@given(lists(scalars))
def test_not_in(arg):
    op = filters.not_in(arg)
    assert isinstance(op, filters.NotIn)

    filter_dict = op.model_dump()
    assert filter_dict == {"$nin": arg}
    assert filters.NotIn.model_validate(filter_dict) == op


# Evaluation ops
@given(text(printable))  # TODO: Generate valid regex expressions
def test_regex(arg):
    op = filters.regex_match(arg)
    assert isinstance(op, filters.Regex)

    filter_dict = op.model_dump()
    assert filter_dict == {"$regex": arg}
    assert filters.Regex.model_validate(filter_dict) == op


@given(text(printable))
def test_contains(arg):
    op = filters.contains(arg)
    assert isinstance(op, filters.Contains)

    filter_dict = op.model_dump()
    assert filter_dict == {"$contains": arg}
    assert filters.Contains.model_validate(filter_dict) == op
