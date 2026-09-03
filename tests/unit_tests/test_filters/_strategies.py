"""Example generation strategies for generic MongoDB filter tests that rely on `hypothesis`."""

from __future__ import annotations

from string import ascii_letters, digits, punctuation
from typing import Any

from hypothesis.strategies import (
    DrawFn,
    booleans,
    composite,
    dictionaries,
    fixed_dictionaries,
    floats,
    from_regex,
    integers,
    lists,
    one_of,
    text,
)
from wandb._filters import FIELD_REGEX

# ------------------------------------------------------------------------------
# For MongoDB filter expressions

field_names = from_regex(FIELD_REGEX)
"""Single, unnested field names, like "my_key", "otherKey", etc."""


field_paths = lists(field_names, min_size=1, max_size=3).map(".".join)
"""Single or nested field paths, like "my_key", "otherKey.wandb", etc."""


finite_floats = floats(
    width=32, allow_nan=False, allow_infinity=False, allow_subnormal=False
)
"""Finite floating-point numbers, like 1.0, 1.5, 0.123, etc."""


ints_or_floats = integers() | finite_floats
"""Integers or finite floats, like 1, 1.5, 2, etc."""

# spaces intentionally allowed
PRINTABLE_CHARS = f"{digits}{ascii_letters}{punctuation}{' '}"


@composite
def printable_text(draw: DrawFn, max_size: int = 100) -> str:
    """Printable ASCII strings, like "Hello, world!", "12345", etc."""
    return draw(text(PRINTABLE_CHARS, max_size=max_size))


@composite
def filter_dicts(draw: DrawFn) -> dict[str, Any]:
    """Valid dicts of MongoDB filter expressions on a specific field.

    Examples:
        {"path.to.field": {"$gt": 1.0}}
        {"other_field": {"$and": [{"price": {"$gt": 1.0}}, {"$lt": 2.0}]}}
    """
    return draw(
        dictionaries(keys=field_paths, values=op_dicts(), min_size=1, max_size=1)
    )


@composite
def comparison_operands(draw: DrawFn) -> bool | int | float | str:
    """Valid scalars in MongoDB comparison filters, like 1.5, "Hello!", True, etc."""
    return draw(booleans() | integers() | finite_floats | printable_text())


@composite
def equality_operands(
    draw: DrawFn,
) -> bool | int | float | str | list[bool | int | float | str]:
    """Valid scalar or array operands for equality filters."""
    return draw(comparison_operands() | lists(comparison_operands()))


@composite
def logical_operands(draw: DrawFn) -> dict[str, Any]:
    """Valid dicts that can be used as the "inner" operand(s) for logical operators."""
    return draw(filter_dicts() | op_dicts())


# logical ops, eg: {"$not": {"$gt": 1.0}}, {"$and": [{"$gt": 1.0}, {"$lt": 2.0}]}, etc.
and_dicts = fixed_dictionaries({"$and": lists(logical_operands())})
or_dicts = fixed_dictionaries({"$or": lists(logical_operands())})
nor_dicts = fixed_dictionaries({"$nor": lists(logical_operands())})
not_dicts = fixed_dictionaries({"$not": logical_operands()})

# comparison ops, eg: {"$gt": 1.0}, {"$lt": 2.0}, {"$in": [1, 2, 3]}, etc.
gt_dicts = fixed_dictionaries({"$gt": comparison_operands()})
lt_dicts = fixed_dictionaries({"$lt": comparison_operands()})
ge_dicts = fixed_dictionaries({"$gte": comparison_operands()})
le_dicts = fixed_dictionaries({"$lte": comparison_operands()})
eq_dicts = fixed_dictionaries({"$eq": equality_operands()})
ne_dicts = fixed_dictionaries({"$ne": equality_operands()})
nin_dicts = fixed_dictionaries({"$nin": lists(comparison_operands())})
in_dicts = fixed_dictionaries({"$in": lists(comparison_operands())})

# element ops, eg: {"$exists": True}, {"$exists": False}, etc.
exists_dicts = fixed_dictionaries({"$exists": booleans()})

# evaluation ops, eg: {"$regex": ".*"}, {"$contains": "hello"}, etc.
regex_dicts = fixed_dictionaries({"$regex": printable_text()})
contains_dicts = fixed_dictionaries({"$contains": printable_text()})

# array ops, eg: {"$all": [1, 2, 3]}, {"$size": 3}, etc.
all_dicts = fixed_dictionaries({"$all": lists(comparison_operands())})
size_dicts = fixed_dictionaries({"$size": integers()})


@composite
def op_dicts(draw: DrawFn) -> dict[str, Any]:
    """Valid dicts of MongoDB operators.

    Examples:
        {"$gt": 1.0}
        {"$and": [{"$gt": 1.0}, {"$lt": 2.0}]}
    """
    return draw(
        one_of(
            # logical ops
            and_dicts | or_dicts | nor_dicts,
            not_dicts,
            # comparison ops
            gt_dicts | lt_dicts | ge_dicts | le_dicts | eq_dicts | ne_dicts,
            nin_dicts | in_dicts,
            # element ops
            exists_dicts,
            # evaluation ops
            regex_dicts | contains_dicts,
            # array ops
            all_dicts | size_dicts,
        )
    )
