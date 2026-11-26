import copy
from unittest import mock

from wandb.sdk.data_types import utils as data_types_utils


def _recording_converter(records):
    """Deterministic stand-in for val_to_json that records its arguments."""

    def convert(run, key, val, namespace=None, ignore_copy_err=None):
        records.append((key, val, namespace, ignore_copy_err))
        return f"converted({key})"

    return convert


def test_history_dict_to_json_converts_without_mutating_caller():
    payload = {"_step": 7, "loss": 0.5, "tag": "train"}
    original = copy.deepcopy(payload)
    records = []

    with mock.patch.object(
        data_types_utils, "val_to_json", side_effect=_recording_converter(records)
    ):
        result = data_types_utils.history_dict_to_json(None, payload)

    assert result == {
        "_step": "converted(_step)",
        "loss": "converted(loss)",
        "tag": "converted(tag)",
    }
    assert result is not payload
    # The caller's dict must not be replaced by wandb-internal values.
    assert payload == original
    # _step is used as the namespace and ignore_copy_err defaults to None.
    assert {record[2] for record in records} == {7}
    assert {record[3] for record in records} == {None}


def test_history_dict_to_json_two_level_nested_does_not_mutate_caller():
    inner = {"accuracy": 0.8}
    payload = {"_step": 2, "nested": {"inner": inner}}
    original = copy.deepcopy(payload)
    nested = payload["nested"]
    records = []

    with mock.patch.object(
        data_types_utils, "val_to_json", side_effect=_recording_converter(records)
    ):
        result = data_types_utils.history_dict_to_json(
            None, payload, step=9, ignore_copy_err=True
        )

    assert result == {
        "_step": "converted(_step)",
        "nested": {"inner": {"accuracy": "converted(accuracy)"}},
    }
    # Neither the top-level nor any nested dict may be the caller's object.
    assert result is not payload
    assert result["nested"] is not nested
    assert result["nested"]["inner"] is not inner
    # The caller's nested objects stay byte-for-byte intact.
    assert payload == original
    assert payload["nested"] is nested
    assert nested["inner"] is inner
    assert inner == {"accuracy": 0.8}
    # The explicit step and ignore_copy_err are forwarded through every level.
    assert {record[2] for record in records} == {9}
    assert {record[3] for record in records} == {True}


def test_history_dict_to_json_explicit_step_without_step_key():
    payload = {"loss": 1.0}
    records = []

    with mock.patch.object(
        data_types_utils, "val_to_json", side_effect=_recording_converter(records)
    ):
        result = data_types_utils.history_dict_to_json(None, payload, step=4)

    assert result == {"loss": "converted(loss)"}
    assert result is not payload
    assert payload == {"loss": 1.0}
    assert {record[2] for record in records} == {4}
