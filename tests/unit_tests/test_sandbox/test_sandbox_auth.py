from __future__ import annotations

from unittest.mock import Mock

import pytest
import wandb.sandbox._auth as sandbox_auth

_VALID_API_KEY = "x" * 40
_SETTINGS_API_KEY = "y" * 40


def _singleton(
    *,
    entity: str | None = "default-entity",
    project: str | None = "default-project",
    api_key: str | None = None,
    mode: str = "online",
    most_recent_active_run=None,
):
    settings = {
        "entity": entity,
        "project": project,
        "api_key": api_key,
        "identity_token_file": None,
        "credentials_file": None,
        "mode": mode,
        "base_url": "https://api.wandb.ai",
        "app_url": "https://wandb.ai",
    }
    singleton = {
        "settings": Mock(spec_set=tuple(settings), **settings),
        "most_recent_active_run": most_recent_active_run,
    }
    return Mock(spec_set=tuple(singleton), **singleton)


def test_override_sandbox_entity_restores_after_exit(
    monkeypatch,
) -> None:
    singleton = _singleton()
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(
        sandbox_auth.wbauth,
        "authenticate_session",
        lambda **kwargs: sandbox_auth.wbauth.AuthApiKey(
            host=kwargs["host"],
            api_key=_VALID_API_KEY,
        ),
    )

    with sandbox_auth.override_sandbox_entity(entity="override-entity"):
        assert sandbox_auth._resolve_wandb_sdk_auth().headers == {
            "x-api-key": _VALID_API_KEY,
            "x-entity-id": "override-entity",
            "x-project-name": "default-project",
        }

    assert sandbox_auth._resolve_wandb_sdk_auth().headers == {
        "x-api-key": _VALID_API_KEY,
        "x-entity-id": "default-entity",
        "x-project-name": "default-project",
    }


def test_resolve_wandb_sdk_auth_delegates_to_authenticate_session(
    monkeypatch,
) -> None:
    singleton = _singleton(api_key=_SETTINGS_API_KEY)
    auth_calls: list[dict[str, object]] = []
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(
        sandbox_auth.wbauth,
        "authenticate_session",
        lambda **kwargs: (
            auth_calls.append(kwargs)
            or sandbox_auth.wbauth.AuthApiKey(
                host=kwargs["host"],
                api_key=_VALID_API_KEY,
            )
        ),
    )

    headers = sandbox_auth._resolve_wandb_sdk_auth()

    assert len(auth_calls) == 1
    assert isinstance(auth_calls[0]["host"], sandbox_auth.wbauth.HostUrl)
    assert auth_calls[0]["host"].url == "https://api.wandb.ai"
    assert auth_calls[0]["host"].app_url == "https://wandb.ai"
    assert auth_calls[0]["source"] == "sandbox"
    assert auth_calls[0]["no_offline"] is True
    assert headers.strategy == "wandb_api_key"
    assert headers.headers == {
        "x-api-key": _VALID_API_KEY,
        "x-entity-id": "default-entity",
        "x-project-name": "default-project",
    }


def test_resolve_wandb_sdk_auth_omits_optional_metadata_when_unset(
    monkeypatch,
) -> None:
    singleton = _singleton(entity=None, project=None)
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(
        sandbox_auth.wbauth,
        "authenticate_session",
        lambda **kwargs: sandbox_auth.wbauth.AuthApiKey(
            host=kwargs["host"],
            api_key=_VALID_API_KEY,
        ),
    )

    headers = sandbox_auth._resolve_wandb_sdk_auth()

    assert headers.headers == {"x-api-key": _VALID_API_KEY}


def test_resolve_wandb_sdk_auth_rejects_non_api_key_credentials(
    monkeypatch,
) -> None:
    singleton = _singleton()
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(
        sandbox_auth.wbauth,
        "authenticate_session",
        lambda **kwargs: sandbox_auth.wbauth.AuthIdentityTokenFile(
            host=kwargs["host"],
            path="/tmp/identity-token",
            credentials_file="/tmp/credentials.json",
        ),
    )

    with pytest.raises(
        sandbox_auth.UsageError,
        match="wandb.sandbox currently supports only W&B user API-key auth.",
    ):
        sandbox_auth._resolve_wandb_sdk_auth()


def test_resolve_wandb_sdk_auth_raises_when_login_does_not_resolve_credentials(
    monkeypatch,
) -> None:
    singleton = _singleton()
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(
        sandbox_auth.wbauth,
        "authenticate_session",
        lambda **kwargs: None,
    )

    with pytest.raises(
        sandbox_auth.CWSandboxAuthenticationError,
        match="wandb.sandbox could not resolve W&B credentials for sandbox auth.",
    ):
        sandbox_auth._resolve_wandb_sdk_auth()
