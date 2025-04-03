from __future__ import annotations

import json
from string import printable
from typing import Any

from hypothesis import given
from hypothesis.strategies import (
    booleans,
    builds,
    fixed_dictionaries,
    lists,
    sampled_from,
    text,
)
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

from ._strategies import filter_expr_dicts, op_dicts, scalars

# ----------------------------------------------------------------------------
# Check round-trip serialization -> deserialization
# ... starting from *validated* (pydantic) types.


# Variadic logical ops
@given(op=builds(And, and_=lists(filter_expr_dicts() | op_dicts())))
def test_and_from_validated_op(op: And):
    assert op.model_dump().keys() == {"$and"}
    assert And.model_validate(op.model_dump()) == op
    assert And.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Or, or_=lists(filter_expr_dicts() | op_dicts())))
def test_or_from_validated_op(op: Or):
    assert op.model_dump().keys() == {"$or"}
    assert Or.model_validate(op.model_dump()) == op
    assert Or.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Nor, nor_=lists(filter_expr_dicts() | op_dicts())))
def test_nor_from_validated_op(op: Nor):
    assert op.model_dump().keys() == {"$nor"}
    assert Nor.model_validate(op.model_dump()) == op
    assert Nor.model_validate_json(op.model_dump_json()) == op


# Unary logical ops
@given(op=builds(Not, not_=filter_expr_dicts() | op_dicts()))
def test_not_from_validated_op(op: Not):
    assert op.model_dump().keys() == {"$not"}
    assert Not.model_validate(op.model_dump()) == op
    assert Not.model_validate_json(op.model_dump_json()) == op


# Comparison ops
@given(op=builds(Gt, gt_=scalars()))
def test_gt_from_validated_op(op: Gt):
    assert op.model_dump().keys() == {"$gt"}
    assert Gt.model_validate(op.model_dump()) == op
    assert Gt.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Lt, lt_=scalars()))
def test_lt_from_validated_op(op: Lt):
    assert op.model_dump().keys() == {"$lt"}
    assert Lt.model_validate(op.model_dump()) == op
    assert Lt.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Gte, gte_=scalars()))
def test_gte_from_validated_op(op: Gte):
    assert op.model_dump().keys() == {"$gte"}
    assert Gte.model_validate(op.model_dump()) == op
    assert Gte.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Lte, lte_=scalars()))
def test_lte_from_validated_op(op: Lte):
    assert op.model_dump().keys() == {"$lte"}
    assert Lte.model_validate(op.model_dump()) == op
    assert Lte.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Eq, eq_=scalars()))
def test_eq_from_validated_op(op: Eq):
    assert op.model_dump().keys() == {"$eq"}
    assert Eq.model_validate(op.model_dump()) == op
    assert Eq.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Ne, ne_=scalars()))
def test_ne_from_validated_op(op: Ne):
    assert op.model_dump().keys() == {"$ne"}
    assert Ne.model_validate(op.model_dump()) == op
    assert Ne.model_validate_json(op.model_dump_json()) == op


@given(op=builds(In, in_=lists(scalars())))
def test_in_from_validated_op(op: In):
    assert op.model_dump().keys() == {"$in"}
    assert In.model_validate(op.model_dump()) == op
    assert In.model_validate_json(op.model_dump_json()) == op


@given(op=builds(NotIn, nin_=lists(scalars())))
def test_not_in_from_validated_op(op: NotIn):
    assert op.model_dump().keys() == {"$nin"}
    assert NotIn.model_validate(op.model_dump()) == op
    assert NotIn.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Exists, exists_=booleans()))
def test_exists_from_validated_op(op: Exists):
    assert op.model_dump().keys() == {"$exists"}
    assert Exists.model_validate(op.model_dump()) == op
    assert Exists.model_validate_json(op.model_dump_json()) == op


# Evaluation ops
@given(op=builds(Regex, regex_=text(printable)))
def test_regex_from_validated_op(op: Regex):
    assert op.model_dump().keys() == {"$regex"}
    assert Regex.model_validate(op.model_dump()) == op
    assert Regex.model_validate_json(op.model_dump_json()) == op


@given(op=builds(Contains, contains_=text(printable)))
def test_contains_from_validated_op(op: Contains):
    assert op.model_dump().keys() == {"$contains"}
    assert Contains.model_validate(op.model_dump()) == op
    assert Contains.model_validate_json(op.model_dump_json()) == op


# ----------------------------------------------------------------------------
# Check round-trip serialization -> deserialization
# ...starting from *unvalidated/serialized* (dict) types.
@given(orig_dict=fixed_dictionaries({"$and": lists(filter_expr_dicts() | op_dicts())}))
def test_and_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == And.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$or": lists(filter_expr_dicts() | op_dicts())}))
def test_or_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Or.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$nor": lists(filter_expr_dicts() | op_dicts())}))
def test_nor_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Nor.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$not": filter_expr_dicts() | op_dicts()}))
def test_not_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Not.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$gt": scalars()}))
def test_gt_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Gt.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$lt": scalars()}))
def test_lt_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Lt.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$gte": scalars()}))
def test_gte_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Gte.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$lte": scalars()}))
def test_lte_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Lte.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$eq": scalars()}))
def test_eq_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Eq.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$ne": scalars()}))
def test_ne_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Ne.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$in": lists(scalars())}))
def test_in_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == In.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$nin": lists(scalars())}))
def test_not_in_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == NotIn.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$exists": booleans()}))
def test_exists_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Exists.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$regex": text(printable)}))
def test_regex_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Regex.model_validate(orig_dict).model_dump()


@given(orig_dict=fixed_dictionaries({"$contains": text(printable)}))
def test_contains_from_dict(orig_dict: dict[str, Any]):
    assert orig_dict == Contains.model_validate(orig_dict).model_dump()


# ----------------------------------------------------------------------------
# Checks on FilterExpr behavior
@given(orig_dict=filter_expr_dicts())
def test_filter_expr_dict_roundtrip(orig_dict: dict[str, Any]):
    assert orig_dict == FilterExpr.model_validate(orig_dict).model_dump()


EXPR_DICTS_WITH_UNKNOWN_OPS = [
    # single unknown op
    {"myField": {"$unknownOp": 1.0}},
    # multiple unknown ops
    {"myField": {"$unknownOp": 1.0, "$otherUnknownOp": "hello"}},
    # mixed unknown and known ops
    {"myField": {"$eq": 1.0, "$unknownOp": "hello"}},
]


@given(orig_dict=sampled_from(EXPR_DICTS_WITH_UNKNOWN_OPS))
def test_filter_expr_dict_roundtrip_with_unknown_ops(orig_dict: dict[str, Any]):
    """Check that we can still roundtrip from/to dicts for unknown or not-yet-implemented MongoDB operators."""
    assert orig_dict == FilterExpr.model_validate(orig_dict).model_dump()
    assert (
        orig_dict == FilterExpr.model_validate_json(json.dumps(orig_dict)).model_dump()
    )


@given(orig_json=sampled_from(EXPR_DICTS_WITH_UNKNOWN_OPS).map(json.dumps))
def test_filter_expr_json_roundtrip_with_unknown_ops(orig_json: str):
    """Check that we can still roundtrip from/to JSON for unknown or not-yet-implemented MongoDB operators."""
    assert json.loads(orig_json) == json.loads(
        FilterExpr.model_validate_json(orig_json).model_dump_json()
    )
    assert json.loads(orig_json) == json.loads(
        FilterExpr.model_validate(json.loads(orig_json)).model_dump_json()
    )
