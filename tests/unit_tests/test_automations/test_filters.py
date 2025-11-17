from __future__ import annotations

import json
from typing import Any

from hypothesis import given
from hypothesis.strategies import booleans, builds, lists, sampled_from
from wandb.automations._filters import (
    And,
    Contains,
    Eq,
    Exists,
    FilterExpr,
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
)
from wandb.automations._filters.filterutils import simplify_expr

from ._strategies import (
    and_dicts,
    comparison_op_operands,
    contains_dicts,
    eq_dicts,
    exists_dicts,
    filter_dicts,
    ge_dicts,
    gt_dicts,
    in_dicts,
    le_dicts,
    logical_op_operands,
    lt_dicts,
    ne_dicts,
    nin_dicts,
    nor_dicts,
    not_dicts,
    or_dicts,
    printable_text,
    regex_dicts,
)

# ----------------------------------------------------------------------------
# Check round-trip serialization -> deserialization
# ... starting from *validated* (pydantic) types.


# Variadic logical ops
@given(op=builds(And, exprs=lists(logical_op_operands)))
def test_and_from_validated_op(op: And):
    assert op.model_dump().keys() == {"$and"}
    assert And.model_validate(op.model_dump()) == op
    assert And.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Or, exprs=lists(logical_op_operands)))
def test_or_from_validated_op(op: Or):
    assert op.model_dump().keys() == {"$or"}
    assert Or.model_validate(op.model_dump()) == op
    assert Or.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Nor, exprs=lists(logical_op_operands)))
def test_nor_from_validated_op(op: Nor):
    assert op.model_dump().keys() == {"$nor"}
    assert Nor.model_validate(op.model_dump()) == op
    assert Nor.model_validate_json(op.model_dump_json()) == op


# Unary logical ops
@given(op=builds(Not, expr=logical_op_operands))
def test_not_from_validated_op(op: Not):
    assert op.model_dump().keys() == {"$not"}
    assert Not.model_validate(op.model_dump()) == op
    assert Not.model_validate_json(op.model_dump_json()) == op


# Comparison ops
@given(op=builds(Gt, val=comparison_op_operands))
def test_gt_from_validated_op(op: Gt):
    assert op.model_dump().keys() == {"$gt"}
    assert Gt.model_validate(op.model_dump()) == op
    assert Gt.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Lt, val=comparison_op_operands))
def test_lt_from_validated_op(op: Lt):
    assert op.model_dump().keys() == {"$lt"}
    assert Lt.model_validate(op.model_dump()) == op
    assert Lt.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Gte, val=comparison_op_operands))
def test_gte_from_validated_op(op: Gte):
    assert op.model_dump().keys() == {"$gte"}
    assert Gte.model_validate(op.model_dump()) == op
    assert Gte.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Lte, val=comparison_op_operands))
def test_lte_from_validated_op(op: Lte):
    assert op.model_dump().keys() == {"$lte"}
    assert Lte.model_validate(op.model_dump()) == op
    assert Lte.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Eq, val=comparison_op_operands))
def test_eq_from_validated_op(op: Eq):
    assert op.model_dump().keys() == {"$eq"}
    assert Eq.model_validate(op.model_dump()) == op
    assert Eq.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Ne, val=comparison_op_operands))
def test_ne_from_validated_op(op: Ne):
    assert op.model_dump().keys() == {"$ne"}
    assert Ne.model_validate(op.model_dump()) == op
    assert Ne.model_validate_json(op.model_dump_json()) == op


@given(op=builds(In, val=lists(comparison_op_operands)))
def test_in_from_validated_op(op: In):
    assert op.model_dump().keys() == {"$in"}
    assert In.model_validate(op.model_dump()) == op
    assert In.model_validate_json(op.model_dump_json()) == op


@given(op=builds(NotIn, val=lists(comparison_op_operands)))
def test_not_in_from_validated_op(op: NotIn):
    assert op.model_dump().keys() == {"$nin"}
    assert NotIn.model_validate(op.model_dump()) == op
    assert NotIn.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Exists, val=booleans()))
def test_exists_from_validated_op(op: Exists):
    assert op.model_dump().keys() == {"$exists"}
    assert Exists.model_validate(op.model_dump()) == op
    assert Exists.model_validate_json(op.model_dump_json()) == op


# Evaluation ops
@given(op=builds(Regex, val=printable_text))
def test_regex_from_validated_op(op: Regex):
    assert op.model_dump().keys() == {"$regex"}
    assert Regex.model_validate(op.model_dump()) == op
    assert Regex.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Contains, val=printable_text))
def test_contains_from_validated_op(op: Contains):
    assert op.model_dump().keys() == {"$contains"}
    assert Contains.model_validate(op.model_dump()) == op
    assert Contains.model_validate_json(op.model_dump_json()) == op


# ----------------------------------------------------------------------------
# Check round-trip serialization -> deserialization
# ...starting from *unvalidated/serialized* (dict) types.
@given(orig_dict=and_dicts)
def test_and_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == And.model_validate(orig_dict).model_dump()


@given(orig_dict=or_dicts)
def test_or_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Or.model_validate(orig_dict).model_dump()


@given(orig_dict=nor_dicts)
def test_nor_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Nor.model_validate(orig_dict).model_dump()


@given(orig_dict=not_dicts)
def test_not_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Not.model_validate(orig_dict).model_dump()


@given(orig_dict=gt_dicts)
def test_gt_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Gt.model_validate(orig_dict).model_dump()


@given(orig_dict=lt_dicts)
def test_lt_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Lt.model_validate(orig_dict).model_dump()


@given(orig_dict=ge_dicts)
def test_gte_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Gte.model_validate(orig_dict).model_dump()


@given(orig_dict=le_dicts)
def test_lte_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Lte.model_validate(orig_dict).model_dump()


@given(orig_dict=eq_dicts)
def test_eq_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Eq.model_validate(orig_dict).model_dump()


@given(orig_dict=ne_dicts)
def test_ne_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Ne.model_validate(orig_dict).model_dump()


@given(orig_dict=in_dicts)
def test_in_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == In.model_validate(orig_dict).model_dump()


@given(orig_dict=nin_dicts)
def test_not_in_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == NotIn.model_validate(orig_dict).model_dump()


@given(orig_dict=exists_dicts)
def test_exists_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Exists.model_validate(orig_dict).model_dump()


@given(orig_dict=regex_dicts)
def test_regex_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Regex.model_validate(orig_dict).model_dump()


@given(orig_dict=contains_dicts)
def test_contains_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Contains.model_validate(orig_dict).model_dump()


# ----------------------------------------------------------------------------
# Checks on FilterExpr behavior
@given(orig_dict=filter_dicts)
def test_filter_expr_dict_roundtrip(orig_dict: dict[str, Any]):
    assert orig_dict == FilterExpr.model_validate(orig_dict).model_dump()


FILTER_DICTS_WTIH_UNKNOWN_KEYS = [
    # single unknown op
    {"myField": {"$unknownOp": 1.0}},
    # multiple unknown ops
    {"myField": {"$unknownOp": 1.0, "$otherUnknownOp": "hello"}},
    # mixed unknown and known ops
    {"myField": {"$eq": 1.0, "$unknownOp": "hello"}},
]


@given(orig_dict=sampled_from(FILTER_DICTS_WTIH_UNKNOWN_KEYS))
def test_filter_dict_roundtrip_with_unknown_ops(orig_dict: dict[str, Any]):
    """Check that we can still roundtrip from/to dicts for unknown or not-yet-implemented MongoDB operators."""
    assert orig_dict == FilterExpr.model_validate(orig_dict).model_dump()
    assert (
        orig_dict == FilterExpr.model_validate_json(json.dumps(orig_dict)).model_dump()
    )


@given(orig_json=sampled_from(FILTER_DICTS_WTIH_UNKNOWN_KEYS).map(json.dumps))
def test_filter_dict_json_roundtrip_with_unknown_ops(orig_json: str):
    """Check that we can still roundtrip from/to JSON for unknown or not-yet-implemented MongoDB operators."""
    assert json.loads(orig_json) == json.loads(
        FilterExpr.model_validate_json(orig_json).model_dump_json()
    )
    assert json.loads(orig_json) == json.loads(
        FilterExpr.model_validate(json.loads(orig_json)).model_dump_json()
    )


# ----------------------------------------------------------------------------
def test_simplify_and_op_with_single_expr():
    expr = FilterExpr(field="a", op=Eq(val=1))
    orig = And(exprs=[expr])
    assert simplify_expr(orig) == expr


def test_simplify_or_op_with_single_expr():
    expr = FilterExpr(field="a", op=Eq(val=1))
    orig = Or(exprs=[expr])
    assert simplify_expr(orig) == expr


def test_simplify_and_op_with_nested_exprs():
    expr1 = FilterExpr(field="a", op=Eq(val=1))
    expr2 = FilterExpr(field="b", op=Eq(val=2))

    orig = And(
        exprs=[
            And(
                exprs=[
                    And(
                        exprs=[
                            expr1,  # Expect to keep this
                        ]
                    )
                ]
            ),
            And(),
            And(exprs=[And(), And()]),
            Or(
                exprs=[
                    expr2,  # Expect to keep this
                ]
            ),
        ],
    )
    expected = And(exprs=[expr1, expr2])
    assert simplify_expr(orig) == expected


def test_simplify_or_op_with_nested_exprs():
    kept_expr1 = FilterExpr(field="a", op=Eq(val=1))
    kept_expr2 = FilterExpr(field="b", op=Eq(val=2))

    orig = Or(
        exprs=[
            Or(
                exprs=[
                    Or(
                        exprs=[
                            kept_expr1,
                        ]
                    )
                ]
            ),
            Or(),
            Or(exprs=[Or(), Or()]),
            And(
                exprs=[
                    kept_expr2,
                ],
            ),
        ],
    )
    expected = Or(exprs=[kept_expr1, kept_expr2])
    assert simplify_expr(orig) == expected


def test_simplify_not_op_on_invertible_ops():
    eq_op = Eq(val=1)
    ne_op = Ne(val=1)

    assert eq_op != ne_op  # sanity check

    assert simplify_expr(Not(expr=eq_op)) == ne_op
    assert simplify_expr(Not(expr=ne_op)) == eq_op

    # TODO: Fill this in + parametrize on other negated operators


def test_simplify_not_op_with_nested_exprs():
    expr = And(
        exprs=[
            FilterExpr(field="a", op=Eq(val=1)),
            FilterExpr(field="b", op=Eq(val=2)),
        ]
    )

    # An even number of nested Not ops should cancel out
    orig = Not(expr=Not(expr=Not(expr=Not(expr=expr))))
    assert simplify_expr(orig) == expr

    # An odd number of nested Not ops should keep a single Not op
    orig = Not(expr=Not(expr=Not(expr=Not(expr=Not(expr=expr)))))
    assert simplify_expr(orig) == Not(expr=expr)
