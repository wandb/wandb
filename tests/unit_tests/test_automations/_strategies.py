"""
Example generation strategies for tests that rely on `hypothesis`.
"""

from __future__ import annotations

from string import ascii_letters, digits, printable
from typing import Any

from hypothesis.strategies import (
    DrawFn,
    SearchStrategy,
    composite,
    deferred,
    fixed_dictionaries,
    floats,
    integers,
    lists,
    one_of,
    text,
)
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
from wandb.sdk.automations._filters.evaluation import Regex
from wandb.sdk.automations._filters.logic import And, Nor, Not, Or


@composite
def field_names(draw: DrawFn) -> SearchStrategy[str]:
    """Strategy to generate field names or nested paths, e.g. "my_field" or "myField.weights_and_biases."""

    # field/key names can contain numbers, just not as the first char(s)
    field_names = text(
        alphabet=(*ascii_letters, *digits, "_"),
        max_size=20,
    ).map(
        lambda s: s.lstrip(digits),
    )
    field_name_seqs = lists(field_names, min_size=1, max_size=3)

    # e.g. ("weights", "and_biases") -> "weights.and_biases"
    return ".".join(draw(field_name_seqs))


comparable_values: SearchStrategy[int | float | str] = one_of(
    integers(),
    floats(allow_nan=False, allow_infinity=False, allow_subnormal=False),
    text(printable, max_size=20),
)


def expr_dicts() -> SearchStrategy[dict[str, Any]]:
    return one_of(
        COMPARISON_OP_DICTS,
        LOGICAL_OP_DICTS,
        EVALUATION_OP_DICTS,
    )


COMPARISON_OP_DICTS: SearchStrategy[dict[str, Any]] = deferred(
    lambda: one_of(
        gt_dicts(),
        lt_dicts(),
        gte_dicts(),
        lte_dicts(),
        eq_dicts(),
        ne_dicts(),
        nin_dicts(),
        in_dicts(),
    )
)
LOGICAL_OP_DICTS: SearchStrategy[dict[str, Any]] = deferred(  # Prevents RecursionError
    lambda: one_of(
        not_dicts(),
        and_dicts(),
        or_dicts(),
        nor_dicts(),
    )
)
EVALUATION_OP_DICTS: SearchStrategy[dict[str, Any]] = deferred(
    lambda: regex_dicts(),
)


def gt_dicts():
    return fixed_dictionaries({Gt.op: comparable_values})


def lt_dicts():
    return fixed_dictionaries({Lt.op: comparable_values})


def gte_dicts():
    return fixed_dictionaries({Gte.op: comparable_values})


def lte_dicts():
    return fixed_dictionaries({Lte.op: comparable_values})


def eq_dicts():
    return fixed_dictionaries({Eq.op: comparable_values})


def ne_dicts():
    return fixed_dictionaries({Ne.op: comparable_values})


def nin_dicts():
    return fixed_dictionaries({NotIn.op: lists(comparable_values)})


def in_dicts():
    return fixed_dictionaries({In.op: lists(comparable_values)})


def regex_dicts():
    return fixed_dictionaries({Regex.op: text()})


def not_dicts():
    return fixed_dictionaries({Not.op: expr_dicts()})


def and_dicts():
    return fixed_dictionaries({And.op: lists(expr_dicts())})


def or_dicts():
    return fixed_dictionaries({Or.op: lists(expr_dicts())})


def nor_dicts():
    return fixed_dictionaries({Nor.op: lists(expr_dicts())})
