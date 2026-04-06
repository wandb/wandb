from __future__ import annotations

import sys
from unittest.mock import Mock

import pytest

if sys.version_info < (3, 11):
    pytest.skip("wandb.sandbox requires Python 3.11+", allow_module_level=True)

import wandb.sandbox._auth as sandbox_auth

_VALID_API_KEY = "x" * 40


@pytest.fixture(autouse=True)
def _clear_explicit_session_auth() -> None:
    sandbox_auth.wbauth.unauthenticate_session(update_settings=False)
    yield
    sandbox_auth.wbauth.unauthenticate_session(update_settings=False)


def _run(entity: str | None, project: str | None):
    data = {"entity": entity, "project": project}
    return Mock(spec_set=tuple(data), **data)


def _singleton(
    *,
    entity: str | None = "default-entity",
    project: str | None = "default-project",
    api_key: str | None = None,
    mode: str = "online",
    offline: bool = False,
    most_recent_active_run=None,
):
    settings = {
        "entity": entity,
        "project": project,
        "api_key": api_key,
        "identity_token_file": None,
        "credentials_file": None,
        "mode": mode,
        "_offline": offline,
        "base_url": "https://api.wandb.ai",
        "app_url": "https://wandb.ai",
    }
    singleton = {
        "settings": Mock(spec_set=tuple(settings), **settings),
        "most_recent_active_run": most_recent_active_run,
    }
    return Mock(spec_set=tuple(singleton), **singleton)


def test_resolve_effective_entity_project_uses_settings_without_run(
    monkeypatch,
) -> None:
    singleton = _singleton()
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(sandbox_auth.wandb, "run", None)

    assert sandbox_auth._resolve_effective_entity_project() == (
        "default-entity",
        "default-project",
    )


def test_resolve_effective_entity_project_prefers_active_run(
    monkeypatch,
) -> None:
    singleton = _singleton()
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(sandbox_auth.wandb, "run", _run("run-entity", "run-project"))

    assert sandbox_auth._resolve_effective_entity_project() == (
        "run-entity",
        "run-project",
    )


def test_resolve_effective_entity_project_uses_most_recent_active_run(
    monkeypatch,
) -> None:
    singleton = _singleton(
        most_recent_active_run=_run("recent-entity", "recent-project")
    )
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(sandbox_auth.wandb, "run", None)

    assert sandbox_auth._resolve_effective_entity_project() == (
        "recent-entity",
        "recent-project",
    )


def test_override_sandbox_entity_is_noop_for_none(
    monkeypatch,
) -> None:
    singleton = _singleton(
        most_recent_active_run=_run("recent-entity", "recent-project")
    )
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(sandbox_auth.wandb, "run", None)

    with sandbox_auth._override_sandbox_entity(entity=None):
        assert sandbox_auth._resolve_effective_entity_project() == (
            "recent-entity",
            "recent-project",
        )


def test_override_sandbox_entity_suppresses_project(
    monkeypatch,
) -> None:
    singleton = _singleton(
        most_recent_active_run=_run("recent-entity", "recent-project")
    )
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(sandbox_auth.wandb, "run", _run("run-entity", "run-project"))

    with sandbox_auth._override_sandbox_entity(entity="override-entity"):
        assert sandbox_auth._resolve_effective_entity_project() == (
            "override-entity",
            None,
        )

    assert sandbox_auth._resolve_effective_entity_project() == (
        "run-entity",
        "run-project",
    )


def test_resolve_wandb_sdk_auth_uses_session_credentials(
    monkeypatch,
) -> None:
    singleton = _singleton()
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(sandbox_auth.wandb, "run", None)
    sandbox_auth.wbauth.use_explicit_auth(
        auth=sandbox_auth.wbauth.AuthApiKey(
            host="https://api.wandb.ai",
            api_key=_VALID_API_KEY,
        ),
        source="test",
    )
    monkeypatch.setattr(
        sandbox_auth.wandb_login,
        "_login",
        lambda **kwargs: pytest.fail("wandb_login._login should not run"),
    )

    headers = sandbox_auth._resolve_wandb_sdk_auth()

    assert headers.strategy == "wandb_api_key"
    assert headers.headers == {
        "x-api-key": _VALID_API_KEY,
        "x-entity-id": "default-entity",
        "x-project-name": "default-project",
    }


def test_resolve_wandb_sdk_auth_falls_back_to_settings_api_key(
    monkeypatch,
) -> None:
    singleton = _singleton(api_key=_VALID_API_KEY)
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(sandbox_auth.wandb, "run", None)
    monkeypatch.setattr(
        sandbox_auth.wandb_login,
        "_login",
        lambda **kwargs: pytest.fail("wandb_login._login should not run"),
    )

    headers = sandbox_auth._resolve_wandb_sdk_auth()

    assert headers.headers["x-api-key"] == _VALID_API_KEY
    assert headers.headers["x-entity-id"] == "default-entity"
    assert headers.headers["x-project-name"] == "default-project"


def test_resolve_wandb_sdk_auth_loads_auth_when_missing(
    monkeypatch,
) -> None:
    singleton = _singleton(
        most_recent_active_run=_run("recent-entity", "recent-project")
    )
    login_calls: list[dict[str, object]] = []
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(sandbox_auth.wandb, "run", None)

    def fake_login(**kwargs) -> None:
        login_calls.append(kwargs)
        sandbox_auth.wbauth.use_explicit_auth(
            auth=sandbox_auth.wbauth.AuthApiKey(
                host="https://api.wandb.ai",
                api_key=_VALID_API_KEY,
            ),
            source="test",
        )

    monkeypatch.setattr(
        sandbox_auth.wandb_login,
        "_login",
        fake_login,
    )

    headers = sandbox_auth._resolve_wandb_sdk_auth()

    assert login_calls == [
        {
            "host": "https://api.wandb.ai",
            "update_api_key": False,
            "_silent": True,
        }
    ]
    assert headers.headers == {
        "x-api-key": _VALID_API_KEY,
        "x-entity-id": "recent-entity",
        "x-project-name": "recent-project",
    }


@pytest.mark.parametrize(
    ("credential_source", "settings_api_key"),
    [
        pytest.param("session_credentials", None, id="session_credentials"),
        pytest.param("settings_api_key", _VALID_API_KEY, id="settings_api_key"),
    ],
)
def test_resolve_wandb_sdk_auth_allows_missing_entity_and_project(
    monkeypatch,
    credential_source: str,
    settings_api_key: str | None,
) -> None:
    singleton = _singleton(
        entity=None,
        project=None,
        api_key=settings_api_key,
    )
    monkeypatch.setattr(sandbox_auth.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(sandbox_auth.wandb, "run", None)

    if credential_source == "session_credentials":
        sandbox_auth.wbauth.use_explicit_auth(
            auth=sandbox_auth.wbauth.AuthApiKey(
                host="https://api.wandb.ai",
                api_key=_VALID_API_KEY,
            ),
            source="test",
        )

    monkeypatch.setattr(
        sandbox_auth.wandb_login,
        "_login",
        lambda **kwargs: pytest.fail("wandb_login._login should not run"),
    )

    headers = sandbox_auth._resolve_wandb_sdk_auth()

    assert headers.strategy == "wandb_api_key"
    assert headers.headers == {"x-api-key": _VALID_API_KEY}
