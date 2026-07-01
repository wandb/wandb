from unittest.mock import MagicMock

import pytest
import yaml
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.internal.settings_static import SettingsStatic


def _make_sender(test_settings, **settings_kwargs) -> SendManager:
    settings = test_settings(settings_kwargs)
    return SendManager(
        settings=SettingsStatic(dict(settings)),
        record_q=MagicMock(),
        result_q=MagicMock(),
        interface=MagicMock(),
        context_keeper=MagicMock(),
    )


def _history_record(*, loss: float | None = None, step: int | None = None) -> pb.Record:
    history = pb.HistoryRecord()
    if loss is not None:
        item = history.item.add()
        item.nested_key.append("loss")
        item.value_json = str(loss)
    if step is not None:
        item = history.item.add()
        item.nested_key.append("_step")
        item.value_json = str(step)
    return pb.Record(history=history)


def _history_with_proto_step(*, loss: float, step: int) -> pb.Record:
    history = pb.HistoryRecord()
    item = history.item.add()
    item.nested_key.append("loss")
    item.value_json = str(loss)
    history.step.num = step
    return pb.Record(history=history)


def test_config_save_preserve_order(tmp_path, test_settings):
    config_file = tmp_path / "config.yaml"
    settings = test_settings({"x_files_dir": str(tmp_path)})
    sender = SendManager(
        settings=SettingsStatic(dict(settings)),
        record_q=MagicMock(),
        result_q=MagicMock(),
        interface=MagicMock(),
        context_keeper=MagicMock(),
    )

    original_config = {"b": 1, "a": 2}
    sender._config_save(original_config)
    with open(config_file) as f:
        saved_config = yaml.safe_load(f)
    saved_config.pop("wandb_version")

    assert saved_config == original_config


@pytest.fixture
def sync_sender(test_settings):
    sender = _make_sender(test_settings, x_sync=True)
    sender._fs = MagicMock()
    sender._run = pb.RunRecord(starting_step=0)
    sender._history_step_initialized = True
    sender._history_step = 0
    return sender


def test_send_history_sync_auto_increments_step(sync_sender):
    sync_sender.send_history(_history_record(loss=0.1))
    sync_sender.send_history(_history_record(loss=0.2))

    calls = sync_sender._fs.push.call_args_list
    assert len(calls) == 2
    assert '"_step": 0' in calls[0].args[1]
    assert '"loss": 0.1' in calls[0].args[1]
    assert '"_step": 1' in calls[1].args[1]
    assert '"loss": 0.2' in calls[1].args[1]


def test_send_history_sync_preserves_existing_step(sync_sender):
    sync_sender.send_history(_history_record(loss=0.1, step=7))

    payload = sync_sender._fs.push.call_args.args[1]
    assert '"_step": 7' in payload
    assert '"loss": 0.1' in payload


def test_send_history_sync_uses_proto_step_field(sync_sender):
    sync_sender.send_history(_history_with_proto_step(loss=0.3, step=5))

    payload = sync_sender._fs.push.call_args.args[1]
    assert '"_step": 5' in payload
    assert '"loss": 0.3' in payload


def test_send_history_sync_rewrites_step_below_starting_step(test_settings):
    sender = _make_sender(test_settings, x_sync=True)
    sender._fs = MagicMock()
    sender._run = pb.RunRecord(starting_step=2)
    sender._history_step_initialized = True
    sender._history_step = 2

    sender.send_history(_history_record(loss=0.4, step=0))

    payload = sender._fs.push.call_args.args[1]
    assert '"_step": 2' in payload


def test_send_history_skips_synthesis_without_x_sync(test_settings):
    sender = _make_sender(test_settings, x_sync=False)
    sender._fs = MagicMock()

    sender.send_history(_history_record(loss=0.5))

    payload = sender._fs.push.call_args.args[1]
    assert "_step" not in payload
    assert '"loss": 0.5' in payload


def test_send_history_skips_synthesis_in_shared_mode(test_settings):
    sender = _make_sender(test_settings, x_sync=True, mode="shared")
    sender._fs = MagicMock()

    sender.send_history(_history_record(loss=0.6))

    payload = sender._fs.push.call_args.args[1]
    assert "_step" not in payload
    assert '"loss": 0.6' in payload
