"""Example generation strategies for tests that rely on `hypothesis`."""

from __future__ import annotations

import re
from base64 import b64encode
from string import ascii_letters, digits, punctuation
from typing import Any, Literal

from hypothesis.strategies import (
    DrawFn,
    SearchStrategy,
    booleans,
    composite,
    deferred,
    dictionaries,
    fixed_dictionaries,
    floats,
    from_regex,
    integers,
    lists,
    one_of,
    text,
)


@composite
def gql_ids(
    draw: DrawFn,
    name: str | SearchStrategy[str] | None = None,
) -> SearchStrategy[str]:
    """GraphQL IDs as base64-encoded strings."""
    if name is None:
        name = text(ascii_letters)

    prefix = draw(name) if isinstance(name, SearchStrategy) else name
    index = draw(integers(min_value=0, max_value=1_000_000))

    return b64encode(f"{prefix}:{index:d}".encode()).decode()


# ------------------------------------------------------------------------------
# For MongoDB filter expressions
FIELD_NAME_REGEX: re.Pattern[str] = re.compile(
    r"""
    \A         # String start, multiline not allowed
    [a-zA-Z_]  # field names must start with a letter or underscore
    \w*        # [a-zA-Z0-9_]* in ASCII mode
    \Z         # String end, multiline not allowed
    """,
    flags=re.VERBOSE | re.ASCII,
)
field_names: SearchStrategy[str] = from_regex(FIELD_NAME_REGEX)
"""Single, unnested field names, like "my_key", "otherKey", etc."""


def field_paths(names: SearchStrategy[str] = field_names) -> SearchStrategy[str]:
    """Single or nested field paths, like "my_key", "otherKey.wandb", etc."""
    # e.g. draw ("weights", "and_biases") -> return "weights.and_biases"
    return lists(names, min_size=1, max_size=3).map(".".join)


def finite_floats(width: Literal[16, 32, 64] = 32) -> SearchStrategy[float]:
    """Finite floating-point numbers, like 1.0, 1.5, 0.123, etc."""
    return floats(
        width=width, allow_nan=False, allow_infinity=False, allow_subnormal=False
    )


def ints_or_floats() -> SearchStrategy[int | float]:
    """Integers or finite floats, like 1, 1.5, 2, etc."""
    return one_of(integers(), finite_floats())


def printable_text(max_size: int = 100) -> SearchStrategy[str]:
    """Printable ASCII strings, like "Hello, world!", "12345", etc."""
    # Exclude whitespace that's not a space, e.g. newlines, tabs, etc.
    allowed = digits + ascii_letters + punctuation + " "
    return text(allowed, max_size=max_size)


def scalars() -> SearchStrategy[bool | int | float | str]:
    """Valid scalars in MongoDB filters, like 1.5, "Hello!", True, etc."""
    return booleans() | integers() | finite_floats() | printable_text()


def filter_expr_dicts() -> SearchStrategy[dict[str, Any]]:
    """Valid dicts of MongoDB filter expressions on a specific field.

    E.g.:
        {"path.to.field": {"$gt": 1.0}}
        {"other_field": {"$and": [{"price": {"$gt": 1.0}}, {"$lt": 2.0}]}}
        etc.
    """
    return dictionaries(keys=field_paths(), values=op_dicts(), min_size=1, max_size=1)


def op_dicts() -> SearchStrategy[dict[str, Any]]:
    """Valid dicts of MongoDB operators.

    E.g.:
        {"$gt": 1.0}
        {"$and": [{"$gt": 1.0}, {"$lt": 2.0}]}
        etc.
    """
    return _OP_DICTS


# Note: `deferred` prevents RecursionErrors
_OP_DICTS: SearchStrategy[dict[str, Any]] = deferred(
    lambda: one_of(
        # logical ops, eg: {"$not": {"$gt": 1.0}}, {"$and": [{"$gt": 1.0}, {"$lt": 2.0}]}, etc.
        fixed_dictionaries({"$and": lists(filter_expr_dicts() | op_dicts())}),
        fixed_dictionaries({"$or": lists(filter_expr_dicts() | op_dicts())}),
        fixed_dictionaries({"$nor": lists(filter_expr_dicts() | op_dicts())}),
        fixed_dictionaries({"$not": filter_expr_dicts() | op_dicts()}),
        # comparison ops, eg: {"$gt": 1.0}, {"$lt": 2.0}, {"$in": [1, 2, 3]}, etc.
        fixed_dictionaries({"$gt": scalars()}),
        fixed_dictionaries({"$lt": scalars()}),
        fixed_dictionaries({"$gte": scalars()}),
        fixed_dictionaries({"$lte": scalars()}),
        fixed_dictionaries({"$eq": scalars()}),
        fixed_dictionaries({"$ne": scalars()}),
        fixed_dictionaries({"$nin": lists(scalars())}),
        fixed_dictionaries({"$in": lists(scalars())}),
        # element ops, eg: {"$exists": True}, {"$exists": False}, etc.
        fixed_dictionaries({"$exists": booleans()}),
        # evaluation ops, eg: {"$regex": ".*"}, {"$contains": "hello"}, etc.
        fixed_dictionaries({"$regex": text()}),
        fixed_dictionaries({"$contains": text()}),
    )
)
