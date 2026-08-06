from unittest import mock

import pytest
import wandb
from wandb.sdk.lib.wbauth import host_url, validation


@pytest.mark.parametrize(
    "key, problems",
    (
        ("", "API key is empty."),
        ("some_prefix-" + "A" * 39, "API key must have 40+ characters, has 39."),
        ("some_prefix-" + "A" * 40, None),
        ("some_prefix-" + "A" * 60, None),
        ("*", "API key may only contain"),
    ),
)
def test_check_api_key(key, problems):
    result = validation.check_api_key(key)

    if problems is None:
        assert result is None
    else:
        assert problems in result

def test_check_api_key_validity_skips_server_when_offline(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_singleton = mock.MagicMock()
    fake_singleton.settings = wandb.Settings(mode="offline")
    monkeypatch.setattr("wandb.sdk.wandb_setup.singleton", lambda: fake_singleton)
    service_api = mock.MagicMock()
    monkeypatch.setattr("wandb.apis.public.service_api.ServiceApi", service_api)

    result = validation.check_api_key_validity(
        host=host_url.HostUrl("https://test-host"),
        api_key="test" * 10,
    )

    assert result is None
    service_api.assert_not_called()


def test_check_identity_token_validity_skips_server_when_offline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    fake_singleton = mock.MagicMock()
    fake_singleton.settings = wandb.Settings(mode="offline")
    monkeypatch.setattr("wandb.sdk.wandb_setup.singleton", lambda: fake_singleton)
    service_api = mock.MagicMock()
    monkeypatch.setattr("wandb.apis.public.service_api.ServiceApi", service_api)

    result = validation.check_identity_token_validity(
        host=host_url.HostUrl("https://test-host"),
        identity_token_file=tmp_path / "token.jwt",
        credentials_file=tmp_path / "credentials.json",
    )

    assert result is None
    service_api.assert_not_called()