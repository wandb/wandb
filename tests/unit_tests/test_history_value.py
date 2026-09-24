"""Tests for `wandb.sdk.interface.history_value`."""

from __future__ import annotations

import math
from typing import Any

import pytest
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.interface.history_value import set_history_value

INT64_MAX = 2**63 - 1
INT64_MIN = -(2**63)


def make_typed_value(value: Any) -> pb.HistoryValue:
    """Return the typed form of one logged value."""
    item = pb.HistoryItem(key="k")
    set_history_value(item, value, json_form=False, typed_form=True)
    return item.value


@pytest.mark.parametrize(
    "value, field, expected",
    [
        (None, "null_value", 0),
        (True, "boolean", True),
        (False, "boolean", False),
        (0, "integer", 0),
        (-7, "integer", -7),
        (0.0, "number", 0.0),
        (1.0, "number", 1.0),
        ("", "text", ""),
        ("hi", "text", "hi"),
        # An int64 above 2^53 keeps its exact value.
        (2**53 + 1, "integer", 2**53 + 1),
        (INT64_MAX, "integer", INT64_MAX),
        (INT64_MIN, "integer", INT64_MIN),
        # Nested values stay as verbatim JSON text.
        ({"a": 1}, "json", '{"a":1}'),
        ([1, 2], "json", "[1,2]"),
        # An int too wide for int64 has no scalar case, so it falls back
        # to JSON text, which still carries the exact value.
        (INT64_MAX + 1, "json", str(INT64_MAX + 1)),
        (INT64_MIN - 1, "json", str(INT64_MIN - 1)),
    ],
)
def test_typed_value_cases(value, field, expected):
    value_pb = make_typed_value(value)

    assert value_pb.WhichOneof("value") == field
    assert getattr(value_pb, field) == expected


def test_typed_value_logged_float_stays_a_float():
    """A logged `1.0` is a float, not an int.

    The JSON form cannot express this, so the two forms diverge here by
    design. See the design doc's "Handling numeric Kinds consistently".
    """
    assert make_typed_value(1.0).WhichOneof("value") == "number"
    assert make_typed_value(1).WhichOneof("value") == "integer"


@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_typed_value_infinities(value):
    value_pb = make_typed_value(value)

    assert value_pb.WhichOneof("value") == "number"
    assert value_pb.number == value


def test_typed_value_nan():
    value_pb = make_typed_value(float("nan"))

    assert value_pb.WhichOneof("value") == "number"
    assert math.isnan(value_pb.number)


def test_typed_value_numpy_scalars():
    np = pytest.importorskip("numpy")

    assert make_typed_value(np.float32(1.5)).number == 1.5
    assert make_typed_value(np.float32(1.5)).WhichOneof("value") == "number"
    assert make_typed_value(np.float64(2.5)).WhichOneof("value") == "number"
    assert make_typed_value(np.int64(7)).WhichOneof("value") == "integer"
    assert make_typed_value(np.int64(7)).integer == 7
    assert make_typed_value(np.bool_(True)).WhichOneof("value") == "boolean"
    assert make_typed_value(np.bool_(True)).boolean is True
    assert math.isnan(make_typed_value(np.float32("nan")).number)


def test_typed_value_numpy_array_is_json():
    np = pytest.importorskip("numpy")

    value_pb = make_typed_value(np.array([1, 2, 3]))

    assert value_pb.WhichOneof("value") == "json"
    assert value_pb.json == "[1,2,3]"


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


def test_json_form_is_shared_with_the_json_case():
    """A json_value case does not encode its JSON text twice."""
    item = pb.HistoryItem(key="k")
    set_history_value(item, {"a": 1}, json_form=True, typed_form=True)

    assert item.value.json == item.value_json


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
    assert item.value.WhichOneof("value") == "integer"


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
        assert item.value.WhichOneof("value") == "number"
        assert item.value.number == 0.5


def test_publish_partial_history_defaults_to_json_only(mock_run, record_q):
    run = mock_run()

    run.log({"loss": 0.5})

    item = partial_history_items(record_q)["loss"]
    assert item.value_json == "0.5"
    assert not item.HasField("value")
