from __future__ import annotations

import string

from hypothesis import example, given, note
from hypothesis.strategies import (
    deferred,
    fixed_dictionaries,
    floats,
    integers,
    lists,
    recursive,
    text,
)
from more_itertools import only
from pytest import mark
from wandb.sdk.automations.expr.logic import And, Or
from wandb.sdk.automations.expr.op import FieldFilter

# ------------------------------------------------------------------------------
# Search strategies for hypothesis

# Field names can contain these characters, but can't start or end with them.
non_prefix_chars = tuple(string.digits + "." + "_")
non_suffix_chars = tuple("." + "_")

field_names = (
    text(
        string.ascii_letters + string.digits + "." + "_",
        max_size=20,
    )
    # Prevent consecutive dots
    .filter(lambda s: ".." not in s)
    .map(
        lambda s: s.lstrip(non_prefix_chars).rstrip(non_suffix_chars),
    )
)

comparable_values = (
    integers()
    | floats(allow_nan=False, allow_infinity=False, allow_subnormal=False)
    | text(string.printable, max_size=20)
)
comparable_containers = lists(comparable_values)


any_expr_dicts = deferred(
    lambda: (comparison_dicts | and_dicts | or_dicts | nor_dicts | not_dicts)
)
nin_dicts = fixed_dictionaries({"$nin": comparable_containers})
in_dicts = fixed_dictionaries({"$in": comparable_containers})
eq_dicts = fixed_dictionaries({"$eq": comparable_values})
ne_dicts = fixed_dictionaries({"$ne": comparable_values})
gt_dicts = fixed_dictionaries({"$gt": comparable_values})
lt_dicts = fixed_dictionaries({"$lt": comparable_values})
gte_dicts = fixed_dictionaries({"$gte": comparable_values})
lte_dicts = fixed_dictionaries({"$lte": comparable_values})

comparison_dicts = (
    nin_dicts
    | in_dicts
    | eq_dicts
    | ne_dicts
    | gt_dicts
    | lt_dicts
    | gte_dicts
    | lte_dicts
)

regex_dicts = fixed_dictionaries({"$regex": text()})

eval_dicts = regex_dicts

not_dicts = fixed_dictionaries({"$not": lists(any_expr_dicts)})

and_dicts = fixed_dictionaries({"$and": lists(any_expr_dicts)})
or_dicts = fixed_dictionaries({"$or": lists(any_expr_dicts)})
nor_dicts = fixed_dictionaries({"$nor": lists(any_expr_dicts)})


NESTED_AND_OP = {
    "$and": [
        {
            "$and": [
                {"$gt": -1.2},
                {"$lte": "3"},
                {"$and": []},
            ]
        },
        {
            "$and": [
                {"$in": [1, 2, 3]},
                {"$nin": [0, 2.5]},
            ]
        },
    ]
}
FLATTENED_AND_OP = {
    "$and": [
        {"$gt": -1.2},
        {"$lte": "3"},
        {"$in": [1, 2, 3]},
        {"$nin": [0, 2.5]},
    ]
}


# ------------------------------------------------------------------------------
@example(orig_filter=NESTED_AND_OP)
@given(
    orig_filter=recursive(
        base=lists(comparison_dicts | eval_dicts),
        extend=lambda exprs: lists(fixed_dictionaries({"$and": exprs})),
    ).map(
        # Ensure the top-level operator is "$and"
        lambda exprs: {"$and": exprs},
    )
)
def test_flattened_and_ops(orig_filter):
    """Check that any level of nested `$and` operators is flattened."""
    note(orig_filter)  # In case of failure

    recovered_filter = And.model_validate(orig_filter).model_dump()

    # Check example
    if orig_filter == NESTED_AND_OP:
        assert recovered_filter == FLATTENED_AND_OP

    # Check that the top-level operator is "$and",
    # but no immediate inner expressions are "$and".
    assert only(recovered_filter.keys()) == "$and"

    for inner_op in recovered_filter["$and"]:
        assert "$and" not in inner_op


@given(
    orig_filter=recursive(
        base=lists(comparison_dicts | eval_dicts),
        extend=lambda exprs: lists(fixed_dictionaries({"$or": exprs})),
    ).map(
        # Ensure the top-level operator is "$or"
        lambda exprs: {"$or": exprs},
    )
)
def test_flattened_or_ops(orig_filter):
    """Check that any level of nested `$or` operators is flattened."""
    note(orig_filter)  # In case of failure

    recovered_filter = Or.model_validate(orig_filter).model_dump()

    # Check that the top-level operator is "$or",
    # but no immediate inner expressions are "$or".
    assert only(recovered_filter.keys()) == "$or"

    for inner_expr in recovered_filter["$or"]:
        assert isinstance(inner_expr, dict)
        assert "$or" not in inner_expr.keys()


@mark.xfail(reason="Not implemented yet", strict=True)
def test_nested_not_ops_are_deduplicated():
    """Check that any consecutively nested `$not` operators are deduplicated."""
    filter_dict = {
        "field": {
            "$and": [
                {
                    "$not": {
                        "$not": {
                            "$gt": -1.2,
                        },
                    }
                }
            ]
        }
    }

    expr = FieldFilter.model_validate(filter_dict)
    assert expr.model_dump() == {
        "field": {
            "$and": [
                {"$gt": -1.2},
            ]
        }
    }
