from pathlib import Path

import pytest
import wandb
from wandb.sdk import wandb_setup
from wandb.sdk.lib import wbauth


@pytest.mark.parametrize("source", ["sagemaker", "environment", "netrc", "session"])
def test_api_key_with_sagemaker_credentials(monkeypatch, source):
    monkeypatch.setenv("SM_TRAINING_ENV", "{}")
    Path("secrets.env").write_text(f"WANDB_API_KEY={'sagemaker' * 5}\n")
    settings = wandb_setup.singleton().settings
    assert settings.api_key == "sagemaker" * 5

    expected = "sagemaker" * 5
    if source == "environment":
        expected = "from_env" * 5
        monkeypatch.setenv("WANDB_API_KEY", expected)
    elif source == "netrc":
        expected = "netrc" * 8
        wbauth.write_netrc_auth(host=settings.base_url, api_key=expected)
    elif source == "session":
        expected = "session" * 6
        wbauth.use_explicit_auth(
            wbauth.AuthApiKey(host=settings.base_url, api_key=expected), source="test"
        )

    assert wandb.api.api_key == expected
