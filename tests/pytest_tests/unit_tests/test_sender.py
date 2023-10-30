from unittest.mock import MagicMock

import yaml
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.internal.settings_static import SettingsStatic


def test_config_save_preserve_order(tmp_path, test_settings):
    config_file = tmp_path / "config.yaml"
    settings = test_settings({"files_dir": str(tmp_path)})
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
