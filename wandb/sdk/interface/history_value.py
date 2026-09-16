"""Encoding of one logged value into a history item.

A history item carries the value in one or both of two forms. `value_json`
is the JSON text. `value` is the typed form, which keeps the type of the
logged value. The `x_history_value_encoding` setting selects the forms.

Both forms carry the same value, because a reader may prefer either one.
"""

from __future__ import annotations

from typing import Any

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

    # A numpy scalar has a scalar kind too. Convert it the way the JSON
    # encoder does, then try once more.
    if util.np is not None and isinstance(value, util.np.generic):
        converted, _ = json_friendly(value, preserve_numpy_nan=True)
        if _set_scalar(item.value, converted):
            return

    # Objects, arrays, wide ints, and everything else with no scalar kind
    # stay as verbatim JSON text.
    item.value.kind = pb.HistoryValue.KIND_JSON
    item.value.json_value = (
        json_text if json_text is not None else json_dumps_safer_history(value)
    )


def _set_scalar(typed: pb.HistoryValue, value: Any) -> bool:
    """Set a scalar kind and its field on a typed history value.

    The kind follows the Python type, so a logged `1.0` stays a float and
    an `int` above 2^53 keeps its exact value.

    Returns False, and leaves `typed` untouched, when the value has no
    scalar kind.
    """
    if value is None:
        typed.kind = pb.HistoryValue.KIND_NULL

    elif isinstance(value, bool):
        # bool is a subclass of int, so it must be tested first.
        typed.kind = pb.HistoryValue.KIND_BOOL
        typed.bool_value = value

    elif isinstance(value, int):
        # A wider int has no kind. It falls back to JSON text, which
        # keeps the exact value.
        if not _INT64_MIN <= value <= _INT64_MAX:
            return False
        typed.kind = pb.HistoryValue.KIND_INT
        typed.int_value = value

    elif isinstance(value, float):
        # NaN and +-Infinity are ordinary IEEE doubles here. The JSON
        # form spells them "NaN", "Infinity" and "-Infinity".
        typed.kind = pb.HistoryValue.KIND_FLOAT
        typed.float_value = value

    elif isinstance(value, str):
        typed.kind = pb.HistoryValue.KIND_STRING
        typed.string_value = value

    else:
        return False

    return True
