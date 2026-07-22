"""Example generation strategies for generic MongoDB filter tests that rely on `hypothesis`."""

from __future__ import annotations

import re
from string import ascii_letters, digits, punctuation
from typing import Any

from hypothesis.strategies import (
    SearchStrategy,
    booleans,
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


field_paths: SearchStrategy[str] = lists(field_names, min_size=1, max_size=3).map(
    ".".join
)
"""Single or nested field paths, like "my_key", "otherKey.wandb", etc."""


finite_floats: SearchStrategy[float] = floats(
    width=32, allow_nan=False, allow_infinity=False, allow_subnormal=False
)
"""Finite floating-point numbers, like 1.0, 1.5, 0.123, etc."""


ints_or_floats: SearchStrategy[int | float] = integers() | finite_floats
"""Integers or finite floats, like 1, 1.5, 2, etc."""


PRINTABLE_CHARS = "".join((digits, ascii_letters, punctuation, " "))

printable_text: SearchStrategy[str] = text(PRINTABLE_CHARS, max_size=100)
"""Printable ASCII strings, like "Hello, world!", "12345", etc."""


# ----------------------------------------------------------------------------
# NOTE: `deferred`, when used below, prevents RecursionErrors
# ----------------------------------------------------------------------------
filter_dicts: SearchStrategy[dict[str, Any]] = deferred(
    lambda: dictionaries(keys=field_paths, values=op_dicts, min_size=1, max_size=1)
)
"""Valid dicts of MongoDB filter expressions on a specific field.

Examples:
    {"path.to.field": {"$gt": 1.0}}
    {"other_field": {"$and": [{"price": {"$gt": 1.0}}, {"$lt": 2.0}]}}
"""

comparison_op_operands: SearchStrategy[bool | int | float | str] = (
    booleans() | integers() | finite_floats | printable_text
)
"""Valid scalars in MongoDB comparison filters, like 1.5, "Hello!", True, etc."""

logical_op_operands: SearchStrategy[dict[str, Any]] = deferred(
    lambda: filter_dicts | op_dicts
)
"""Valid dicts that can be used as the "inner" operand(s) for logical operators."""

# logical ops, eg: {"$not": {"$gt": 1.0}}, {"$and": [{"$gt": 1.0}, {"$lt": 2.0}]}, etc.
and_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$and": lists(logical_op_operands)}
)
or_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$or": lists(logical_op_operands)}
)
nor_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$nor": lists(logical_op_operands)}
)
not_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$not": logical_op_operands}
)

# comparison ops, eg: {"$gt": 1.0}, {"$lt": 2.0}, {"$in": [1, 2, 3]}, etc.
gt_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$gt": comparison_op_operands}
)
lt_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$lt": comparison_op_operands}
)
ge_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$gte": comparison_op_operands}
)
le_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$lte": comparison_op_operands}
)
eq_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$eq": comparison_op_operands}
)
ne_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$ne": comparison_op_operands}
)
nin_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$nin": lists(comparison_op_operands)}
)
in_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$in": lists(comparison_op_operands)}
)

# element ops, eg: {"$exists": True}, {"$exists": False}, etc.
exists_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$exists": booleans()}
)

# evaluation ops, eg: {"$regex": ".*"}, {"$contains": "hello"}, etc.
regex_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$regex": printable_text}
)
contains_dicts: SearchStrategy[dict[str, Any]] = fixed_dictionaries(
    {"$contains": printable_text}
)


op_dicts: SearchStrategy[dict[str, Any]] = one_of(
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
)
"""Valid dicts of MongoDB operators.

Examples:
    {"$gt": 1.0}
    {"$and": [{"$gt": 1.0}, {"$lt": 2.0}]}
"""
