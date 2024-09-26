from __future__ import annotations

import string

from hypothesis import example, given, note
from hypothesis.strategies import (
    SearchStrategy,
    deferred,
    fixed_dictionaries,
    floats,
    integers,
    lists,
    recursive,
    text,
)
from pytest import mark
from wandb.sdk.automations._ops.logic import And, Or
from wandb.sdk.automations._ops.op import FieldFilter

# ------------------------------------------------------------------------------
# Search strategies for hypothesis

# Queried/filtered field names can contain these characters, but can't start or end with them.
SEP_CHARS = (".", "_")  # Valid "separator" characters in a field name/path
CANNOT_PREFIX = (*string.digits, *SEP_CHARS)
CANNOT_SUFFIX = SEP_CHARS

field_names: SearchStrategy[str] = (
    text(
        (*string.ascii_letters, *string.digits, *SEP_CHARS),
        max_size=20,
    )
    .filter(lambda s: ".." not in s)  # Exclude consecutive dots
    .map(
        lambda s: s.lstrip(CANNOT_PREFIX).rstrip(CANNOT_SUFFIX)
    )  # Remove invalid prefix/suffix chars
)

comparable_values = (
    integers()
    | floats(allow_nan=False, allow_infinity=False, allow_subnormal=False)
    | text(string.printable, max_size=20)
)
comparable_containers = lists(comparable_values)


any_expr_dicts = deferred(
    lambda: (any_comparison_dicts | any_logic_dicts | any_eval_dicts)
)
any_comparison_dicts = deferred(
    lambda: (
        nin_dicts
        | in_dicts
        | eq_dicts
        | ne_dicts
        | gt_dicts
        | lt_dicts
        | gte_dicts
        | lte_dicts
    )
)
any_eval_dicts = deferred(lambda: regex_dicts)
any_logic_dicts = deferred(lambda: not_dicts | and_dicts | or_dicts | nor_dicts)

nin_dicts = fixed_dictionaries({"$nin": comparable_containers})
in_dicts = fixed_dictionaries({"$in": comparable_containers})
eq_dicts = fixed_dictionaries({"$eq": comparable_values})
ne_dicts = fixed_dictionaries({"$ne": comparable_values})
gt_dicts = fixed_dictionaries({"$gt": comparable_values})
lt_dicts = fixed_dictionaries({"$lt": comparable_values})
gte_dicts = fixed_dictionaries({"$gte": comparable_values})
lte_dicts = fixed_dictionaries({"$lte": comparable_values})

regex_dicts = fixed_dictionaries({"$regex": text()})

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
        base=lists(any_comparison_dicts | any_eval_dicts),
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
    assert recovered_filter.keys() == {"$and"}

    for inner_op in recovered_filter["$and"]:
        assert "$and" not in inner_op


@given(
    orig_filter=recursive(
        base=lists(any_comparison_dicts | any_eval_dicts),
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
    assert recovered_filter.keys() == {"$or"}

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
