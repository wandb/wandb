"""Tests for `wandb.sdk.interface.history_value`.

The tests at the end cover the wiring in `publish_partial_history()`,
which picks the forms from the `x_history_value_encoding` setting.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.interface.history_value import set_history_value

Kind = pb.HistoryValue.Kind

INT64_MAX = 2**63 - 1
INT64_MIN = -(2**63)


def typed(value: Any) -> pb.HistoryValue:
    """Return the typed form of one logged value."""
    item = pb.HistoryItem(key="k")
    set_history_value(item, value, json_form=False, typed_form=True)
    return item.value


@pytest.mark.parametrize(
    "value, kind, field, expected",
    [
        (None, Kind.KIND_NULL, None, None),
        (True, Kind.KIND_BOOL, "bool_value", True),
        (False, Kind.KIND_BOOL, "bool_value", False),
        (0, Kind.KIND_INT, "int_value", 0),
        (-7, Kind.KIND_INT, "int_value", -7),
        (0.0, Kind.KIND_FLOAT, "float_value", 0.0),
        (1.0, Kind.KIND_FLOAT, "float_value", 1.0),
        ("", Kind.KIND_STRING, "string_value", ""),
        ("hi", Kind.KIND_STRING, "string_value", "hi"),
        # An int64 above 2^53 keeps its exact value.
        (2**53 + 1, Kind.KIND_INT, "int_value", 2**53 + 1),
        (INT64_MAX, Kind.KIND_INT, "int_value", INT64_MAX),
        (INT64_MIN, Kind.KIND_INT, "int_value", INT64_MIN),
        # Nested values stay as verbatim JSON text.
        ({"a": 1}, Kind.KIND_JSON, "json_value", '{"a":1}'),
        ([1, 2], Kind.KIND_JSON, "json_value", "[1,2]"),
        # An int too wide for int64 has no kind, so it falls back to JSON
        # text, which still carries the exact value.
        (INT64_MAX + 1, Kind.KIND_JSON, "json_value", str(INT64_MAX + 1)),
        (INT64_MIN - 1, Kind.KIND_JSON, "json_value", str(INT64_MIN - 1)),
    ],
)
def test_typed_value_kinds(value, kind, field, expected):
    value_pb = typed(value)

    assert value_pb.kind == kind
    if field is not None:
        assert getattr(value_pb, field) == expected


def test_typed_value_logged_float_stays_a_float():
    """A logged `1.0` is a float, not an int.

    The JSON form cannot express this, so the two forms diverge here by
    design. See the design doc's "Handling numeric Kinds consistently".
    """
    assert typed(1.0).kind == Kind.KIND_FLOAT
    assert typed(1).kind == Kind.KIND_INT


@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_typed_value_infinities(value):
    value_pb = typed(value)

    assert value_pb.kind == Kind.KIND_FLOAT
    assert value_pb.float_value == value


def test_typed_value_nan():
    value_pb = typed(float("nan"))

    assert value_pb.kind == Kind.KIND_FLOAT
    assert math.isnan(value_pb.float_value)


def test_typed_value_numpy_scalars():
    np = pytest.importorskip("numpy")

    assert typed(np.float32(1.5)).float_value == 1.5
    assert typed(np.float32(1.5)).kind == Kind.KIND_FLOAT
    assert typed(np.float64(2.5)).kind == Kind.KIND_FLOAT
    assert typed(np.int64(7)).kind == Kind.KIND_INT
    assert typed(np.int64(7)).int_value == 7
    assert typed(np.bool_(True)).kind == Kind.KIND_BOOL
    assert typed(np.bool_(True)).bool_value is True
    assert math.isnan(typed(np.float32("nan")).float_value)


def test_typed_value_numpy_array_is_json():
    np = pytest.importorskip("numpy")

    value_pb = typed(np.array([1, 2, 3]))

    assert value_pb.kind == Kind.KIND_JSON
    assert value_pb.json_value == "[1,2,3]"


@pytest.mark.parametrize(
    "value",
    [None, True, 1, 1.5, "hi", {"a": 1}, [1, 2], 2**70, float("nan")],
)
def test_json_form_is_unchanged_by_the_typed_form(value):
    """Writing both forms does not change the JSON form."""
    json_only = pb.HistoryItem(key="k")
    set_history_value(json_only, value, json_form=True, typed_form=False)

    both = pb.HistoryItem(key="k")
    set_history_value(both, value, json_form=True, typed_form=True)

    assert both.value_json == json_only.value_json


def test_json_form_is_shared_with_the_json_kind():
    """A JSON-kind value does not encode its JSON text twice."""
    item = pb.HistoryItem(key="k")
    set_history_value(item, {"a": 1}, json_form=True, typed_form=True)

    assert item.value.json_value == item.value_json


def test_neither_form_leaves_the_item_empty():
    item = pb.HistoryItem(key="k")
    set_history_value(item, 1, json_form=False, typed_form=False)

    assert item.value_json == ""
    assert not item.HasField("value")


def test_json_form_only_does_not_set_the_typed_value():
    item = pb.HistoryItem(key="k")
    set_history_value(item, 1, json_form=True, typed_form=False)

    assert item.value_json == "1"
    assert not item.HasField("value")


def test_typed_form_only_does_not_set_the_json_value():
    item = pb.HistoryItem(key="k")
    set_history_value(item, 1, json_form=False, typed_form=True)

    assert item.value_json == ""
    assert item.value.kind == Kind.KIND_INT


def partial_history_items(record_q) -> dict[str, pb.HistoryItem]:
    """Return the history items of the first partial-history record queued."""
    while True:
        record = record_q.get(timeout=5)
        if record.request.HasField("partial_history"):
            return {item.key: item for item in record.request.partial_history.item}


@pytest.mark.parametrize(
    "encoding, want_json, want_typed",
    [
        ("json", True, False),
        ("typed", False, True),
        ("json,typed", True, True),
    ],
)
def test_publish_partial_history_honors_the_setting(
    mock_run,
    record_q,
    encoding,
    want_json,
    want_typed,
):
    run = mock_run(settings={"x_history_value_encoding": encoding})

    run.log({"loss": 0.5})

    item = partial_history_items(record_q)["loss"]
    assert bool(item.value_json) is want_json
    assert item.HasField("value") is want_typed
    if want_typed:
        assert item.value.kind == Kind.KIND_FLOAT
        assert item.value.float_value == 0.5


def test_publish_partial_history_defaults_to_json_only(mock_run, record_q):
    run = mock_run()

    run.log({"loss": 0.5})

    item = partial_history_items(record_q)["loss"]
    assert item.value_json == "0.5"
    assert not item.HasField("value")
