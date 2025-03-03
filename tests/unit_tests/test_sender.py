import glob
from unittest.mock import MagicMock

import pytest
import yaml
from wandb import Settings
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.internal.settings_static import SettingsStatic


def test_config_save_preserve_order(tmp_path, test_settings):
    config_file = tmp_path / "config.yaml"
    settings = test_settings({"x_files_dir": str(tmp_path)})
    sender = SendManager(
        settings=SettingsStatic(settings.to_proto()),
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


@pytest.mark.skip_wandb_core
@pytest.mark.parametrize(
    "file_path",
    [
        "file_with_*.txt",
        "file_with_?.txt",
        "file_with_[.txt",
    ],
)
def test_send_file_with_glob_characters_is_escaped(tmp_path, file_path):
    dir_watcher = MagicMock()
    sender = SendManager(
        settings=SettingsStatic(Settings(x_files_dir=str(tmp_path)).to_proto()),
        record_q=MagicMock(),
        result_q=MagicMock(),
        interface=MagicMock(),
        context_keeper=MagicMock(),
    )
    sender._dir_watcher = dir_watcher

    files_record = pb.FilesRecord()
    files_record.files.append(
        pb.FilesItem(path=file_path, policy=pb.FilesItem.PolicyType.NOW)
    )
    record = pb.Record()
    record.files.CopyFrom(files_record)

    sender.send_files(record)
    assert dir_watcher.update_policy.call_count == 1
    assert dir_watcher.update_policy.call_args[0][0] == glob.escape(file_path)
    assert str(dir_watcher.update_policy.call_args[0][1]) == "now"
