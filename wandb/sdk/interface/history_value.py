"""Encoding of one logged value into a history item."""

from __future__ import annotations

from typing import Any

from google.protobuf.struct_pb2 import NULL_VALUE

from wandb import util
from wandb.proto import wandb_internal_pb2 as pb
from wandb.util import json_dumps_safer_history, json_friendly

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def set_history_value(
    item: pb.HistoryItem,
    value: Any,
    *,
    json_form: bool,
    typed_form: bool,
) -> None:
    """Write one logged value into a history item.

    `json_form` writes `value_json`. `typed_form` writes `value`.
    """
    json_text: str | None = None

    if json_form:
        json_text = json_dumps_safer_history(value)
        item.value_json = json_text

    if not typed_form:
        return

    if _set_scalar(item.value, value):
        return

    # Convert numpy scalars the way the JSON encoder does.
    if util.np is not None and isinstance(value, util.np.generic):
        converted, _ = json_friendly(value, preserve_numpy_nan=True)
        if _set_scalar(item.value, converted):
            return

    # Objects, arrays, wide ints, and everything else with no scalar case
    # stay as verbatim JSON text.
    item.value.json = (
        json_text if json_text is not None else json_dumps_safer_history(value)
    )


def _set_scalar(typed: pb.HistoryValue, value: Any) -> bool:
    """Set a scalar oneof case on a typed history value.

    The case follows the Python type, so a logged `1.0` stays a float and
    an `int` above 2^53 keeps its exact value.

    Returns False, and leaves `typed` untouched, when the value has no
    scalar case.
    """
    if value is None:
        typed.none = NULL_VALUE

    elif isinstance(value, bool):
        # bool is a subclass of int, so it must be tested first.
        typed.boolean = value

    elif isinstance(value, int):
        # A wider int has no scalar case. It falls back to JSON text, which
        # keeps the exact value.
        if not _INT64_MIN <= value <= _INT64_MAX:
            return False
        typed.integer = value

    elif isinstance(value, float):
        # NaN and +-Infinity are ordinary IEEE doubles here. The JSON
        # form spells them "NaN", "Infinity" and "-Infinity".
        typed.number = value

    elif isinstance(value, str):
        typed.text = value

    else:
        return False

    return True
