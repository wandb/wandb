"""
Example generation strategies for tests that rely on `hypothesis`.
"""

from __future__ import annotations

import re
from string import printable
from typing import Any, Literal

from hypothesis.strategies import (
    DrawFn,
    SearchStrategy,
    booleans,
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
from wandb.sdk.automations.filters._operators import Scalar

FIELD_NAME_REGEX: re.Pattern[str] = re.compile(
    r"""
    \A   # String start, multiline not allowed
    \D   # field names cannot *start* with digits
    \w+  # [a-zA-Z0-9_]+ in ASCII mode
    \Z   # String end, multiline not allowed
    """,
    flags=re.VERBOSE | re.ASCII,
)
field_names: SearchStrategy[str] = from_regex(FIELD_NAME_REGEX)
"""Generates valid, non-nested field names, e.g. "my_field", "otherField", etc."""


@composite
def field_paths(
    draw: DrawFn, names: SearchStrategy[str] = field_names
) -> SearchStrategy[str]:
    """Generates single or nested field names, e.g. "my_field", "myField.weights_and_biases", etc."""
    # e.g. draw ("weights", "and_biases") -> return "weights.and_biases"
    path_parts = draw(lists(names, min_size=1, max_size=3))
    return ".".join(path_parts)


def finite_floats(width: Literal[16, 32, 64] = 32) -> SearchStrategy[float]:
    """Generates finite floating-point numbers, e.g. 1.0, 1.5, 2.0, etc."""
    return floats(
        width=width, allow_nan=False, allow_infinity=False, allow_subnormal=False
    )


def printable_text(max_size: int = 100) -> SearchStrategy[str]:
    """Generates printable ASCII strings, e.g. "Hello, world!", "12345", etc."""
    return text(printable, max_size=max_size)


scalars: SearchStrategy[Scalar] = one_of(
    integers(),
    finite_floats(),
    printable_text(),
    booleans(),
)
"""Generates valid scalar values, e.g. 1, 1.5, "Hello, world!", True, etc."""


def expr_dicts() -> SearchStrategy[dict[str, Any]]:
    """Generates valid MongoDB operator dicts, e.g. {"$gt": 1.0}, {"$and": [{"$gt": 1.0}, {"$lt": 2.0}]}, etc."""
    return one_of(COMPARISON_OP_DICTS, LOGICAL_OP_DICTS, EVALUATION_OP_DICTS)


# Note: Using `deferred` in strategies below prevents RecursionErrors
COMPARISON_OP_DICTS: SearchStrategy[dict[str, Any]] = deferred(
    lambda: one_of(
        fixed_dictionaries({"$gt": scalars}),
        fixed_dictionaries({"$lt": scalars}),
        fixed_dictionaries({"$gte": scalars}),
        fixed_dictionaries({"$lte": scalars}),
        fixed_dictionaries({"$eq": scalars}),
        fixed_dictionaries({"$ne": scalars}),
        fixed_dictionaries({"$nin": lists(scalars)}),
        fixed_dictionaries({"$in": lists(scalars)}),
    )
)
"""Generates valid MongoDB comparison operator dicts, e.g. {"$gt": 1.0}, {"$lt": 2.0}, {"$in": [1, 2, 3]}, etc."""

LOGICAL_OP_DICTS: SearchStrategy[dict[str, Any]] = deferred(
    lambda: one_of(
        fixed_dictionaries({"$not": expr_dicts()}),
        fixed_dictionaries({"$and": lists(expr_dicts())}),
        fixed_dictionaries({"$or": lists(expr_dicts())}),
        fixed_dictionaries({"$nor": lists(expr_dicts())}),
    )
)
"""Generates valid MongoDB logical operator dicts, e.g. {"$not": {"$gt": 1.0}}, {"$and": [{"$gt": 1.0}, {"$lt": 2.0}]}, etc."""

EVALUATION_OP_DICTS: SearchStrategy[dict[str, Any]] = deferred(
    lambda: one_of(
        fixed_dictionaries({"$regex": text()}),
        fixed_dictionaries({"$contains": text()}),
    )
)
"""Generates valid MongoDB evaluation operator dicts, e.g. {"$regex": ".*"}, {"$contains": "hello"}, etc."""
