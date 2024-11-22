"""
Example generation strategies for tests that rely on `hypothesis`.
"""

from __future__ import annotations

import re
from string import printable
from typing import Any

from hypothesis.strategies import (
    DrawFn,
    SearchStrategy,
    composite,
    deferred,
    fixed_dictionaries,
    floats,
    from_regex,
    integers,
    lists,
    one_of,
    text,
)
from wandb.sdk.automations import filters

FIELD_NAME_PATTERN: re.Pattern[str] = re.compile(
    r"""
    \A   # String start, multiline not allowed
    \D   # field names cannot start with digits
    \w+  # [a-zA-Z0-9_]+ in ASCII mode
    \Z   # String end, multiline not allowed
    """,
    flags=re.VERBOSE | re.ASCII,
)
FIELD_NAMES: SearchStrategy[str] = from_regex(FIELD_NAME_PATTERN)


@composite
def field_names_or_paths(draw: DrawFn) -> SearchStrategy[str]:
    """Strategy to generate field names or nested paths, e.g. "my_field" or "myField.weights_and_biases."""

    field_path_seqs = lists(FIELD_NAMES, min_size=1, max_size=3)

    # e.g. ("weights", "and_biases") -> "weights.and_biases"
    return ".".join(draw(field_path_seqs))


finite_floats: SearchStrategy[float] = floats(
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=False,
)
printable_text: SearchStrategy[str] = text(
    printable,
    max_size=100,
)

scalars: SearchStrategy[int | float | str] = one_of(
    integers(),
    finite_floats,
    printable_text,
)


def expr_dicts() -> SearchStrategy[dict[str, Any]]:
    return one_of(
        COMPARISON_OP_DICTS,
        LOGICAL_OP_DICTS,
        EVALUATION_OP_DICTS,
    )


COMPARISON_OP_DICTS: SearchStrategy[dict[str, Any]] = deferred(
    lambda: one_of(
        fixed_dictionaries({filters.Gt.OP: scalars}),
        fixed_dictionaries({filters.Lt.OP: scalars}),
        fixed_dictionaries({filters.Gte.OP: scalars}),
        fixed_dictionaries({filters.Lte.OP: scalars}),
        fixed_dictionaries({filters.Eq.OP: scalars}),
        fixed_dictionaries({filters.Ne.OP: scalars}),
        fixed_dictionaries({filters.NotIn.OP: lists(scalars)}),
        fixed_dictionaries({filters.In.OP: lists(scalars)}),
    )
)
LOGICAL_OP_DICTS: SearchStrategy[dict[str, Any]] = deferred(  # Prevents RecursionError
    lambda: one_of(
        fixed_dictionaries({filters.Not.OP: expr_dicts()}),
        fixed_dictionaries({filters.And.OP: lists(expr_dicts())}),
        fixed_dictionaries({filters.Or.OP: lists(expr_dicts())}),
        fixed_dictionaries({filters.Nor.OP: lists(expr_dicts())}),
    )
)
EVALUATION_OP_DICTS: SearchStrategy[dict[str, Any]] = deferred(
    lambda: fixed_dictionaries({filters.Regex.OP: text()}),
)
