from __future__ import annotations

from hypothesis import given
from hypothesis.strategies import lists
from wandb.sdk.automations import and_, eq, gt, gte, lt, lte, ne, nor_, not_, or_
from wandb.sdk.automations._filters.comparison import (
    Eq,
    Gt,
    Gte,
    In,
    Lt,
    Lte,
    Ne,
    NotIn,
)
from wandb.sdk.automations._filters.funcs import in_, not_in
from wandb.sdk.automations._filters.logic import And, Nor, Not, Or

from ._strategies import comparable_values, expr_dicts

# TODO: Test for lossless round-trip encoding/decoding


# Variadic logical ops
@given(lists(expr_dicts()))
def test_or(args):
    assert isinstance(or_(*args), Or)


@given(lists(expr_dicts()))
def test_and(args):
    assert isinstance(and_(*args), And)


@given(lists(expr_dicts()))
def test_nor(args):
    assert isinstance(nor_(*args), Nor)


# Unary logical ops
@given(expr_dicts())
def test_not(arg):
    assert isinstance(not_(arg), Not)


# Comparison ops
@given(comparable_values)
def test_gt(arg):
    assert isinstance(gt(arg), Gt)


@given(comparable_values)
def test_lt(arg):
    assert isinstance(lt(arg), Lt)


@given(comparable_values)
def test_gte(arg):
    assert isinstance(gte(arg), Gte)


@given(comparable_values)
def test_lte(arg):
    assert isinstance(lte(arg), Lte)


@given(comparable_values)
def test_eq(arg):
    assert isinstance(eq(arg), Eq)


@given(comparable_values)
def test_ne(arg):
    assert isinstance(ne(arg), Ne)


@given(lists(comparable_values))
def test_in(arg):
    assert isinstance(in_(arg), In)


@given(lists(comparable_values))
def test_not_in(arg):
    assert isinstance(not_in(arg), NotIn)
