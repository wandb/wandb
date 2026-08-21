import json
from unittest.mock import MagicMock

import yaml
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.internal.settings_static import SettingsStatic


def _make_sender(test_settings):
    settings = test_settings({"mode": "offline"})
    return SendManager(
        settings=SettingsStatic(dict(settings)),
        record_q=MagicMock(),
        result_q=MagicMock(),
        interface=MagicMock(),
    )


def test_config_save_preserve_order(tmp_path, test_settings):
    config_file = tmp_path / "config.yaml"
    settings = test_settings({"x_files_dir": str(tmp_path)})
    sender = SendManager(
        settings=SettingsStatic(dict(settings)),
        record_q=MagicMock(),
        result_q=MagicMock(),
        interface=MagicMock(),
    )

    original_config = {"b": 1, "a": 2}
    sender._config_save(original_config)
    with open(config_file) as f:
        saved_config = yaml.safe_load(f)
    saved_config.pop("wandb_version")

    assert saved_config == original_config


def test_send_history_skips_renumbering_without_reassign_flag(test_settings):
    sender = _make_sender(test_settings)
    sender._run = pb.RunRecord(sync_may_reassign_steps=False)
    saved: list[dict] = []
    sender._save_history = saved.append

    history = pb.HistoryRecord()
    item = history.item.add()
    item.nested_key.extend(["loss"])
    item.value_json = json.dumps(0.1)

    record = pb.Record()
    record.history.CopyFrom(history)
    sender.send_history(record)

    assert saved == [{"loss": 0.1}]


def test_send_history_renumbers_with_reassign_flag(test_settings):
    sender = _make_sender(test_settings)
    sender._run = pb.RunRecord(sync_may_reassign_steps=True, starting_step=0)
    saved: list[dict] = []
    sender._save_history = saved.append

    history = pb.HistoryRecord()
    item = history.item.add()
    item.nested_key.extend(["loss"])
    item.value_json = json.dumps(0.1)

    record = pb.Record()
    record.history.CopyFrom(history)
    sender.send_history(record)

    assert saved[0]["_step"] == 0
    assert saved[0]["loss"] == 0.1
