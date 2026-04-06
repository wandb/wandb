from __future__ import annotations

import importlib
import sys
import types

import pytest

if sys.version_info < (3, 11):
    pytest.skip("wandb.sandbox requires Python 3.11+", allow_module_level=True)

import cwsandbox

_VALID_API_KEY = "x" * 40


def _import_sandbox_auth(monkeypatch):
    registered: dict[str, object | None] = {"name": None, "func": None}

    def set_auth_mode(name: str, func) -> None:
        registered["name"] = name
        registered["func"] = func

    monkeypatch.setattr(cwsandbox, "set_auth_mode", set_auth_mode)
    monkeypatch.delitem(sys.modules, "wandb.sandbox", raising=False)
    monkeypatch.delitem(sys.modules, "wandb.sandbox._auth", raising=False)

    auth_module = importlib.import_module("wandb.sandbox._auth")
    auth_module.wbauth.unauthenticate_session(update_settings=False)
    return auth_module, registered


def _run(entity: str | None, project: str | None):
    return types.SimpleNamespace(entity=entity, project=project)


def _singleton(
    *,
    entity: str | None = "default-entity",
    project: str | None = "default-project",
    api_key: str | None = None,
    most_recent_active_run=None,
):
    return types.SimpleNamespace(
        settings=types.SimpleNamespace(
            entity=entity,
            project=project,
            api_key=api_key,
            base_url="https://api.wandb.ai",
            app_url="https://wandb.ai",
        ),
        most_recent_active_run=most_recent_active_run,
    )


def test_wandb_sandbox_import_requires_python_3_11(monkeypatch) -> None:
    import wandb as wandb_module

    monkeypatch.setattr(sys, "version_info", (3, 10, 0))
    monkeypatch.delitem(sys.modules, "wandb.sandbox", raising=False)
    monkeypatch.delitem(sys.modules, "wandb.sandbox._auth", raising=False)
    monkeypatch.delattr(wandb_module, "sandbox", raising=False)

    with pytest.raises(ImportError, match=r"Python 3\.11 or newer"):
        importlib.import_module("wandb.sandbox")


def test_import_registers_wandb_auth_mode(monkeypatch) -> None:
    auth_module, registered = _import_sandbox_auth(monkeypatch)

    assert registered["name"] == auth_module._AUTH_MODE_NAME
    assert registered["func"] is auth_module._resolve_wandb_sdk_auth
    assert not hasattr(auth_module, "override_auth_context")
    assert not hasattr(auth_module, "override_sandbox_entity")
    assert not hasattr(auth_module, "register_wandb_auth_mode")


def test_resolve_effective_entity_project_uses_settings_without_run(
    monkeypatch,
) -> None:
    auth_module, _ = _import_sandbox_auth(monkeypatch)
    singleton = _singleton()
    monkeypatch.setattr(auth_module.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(auth_module.wandb, "run", None)

    assert auth_module._resolve_effective_entity_project() == (
        "default-entity",
        "default-project",
    )


def test_resolve_effective_entity_project_prefers_active_run(
    monkeypatch,
) -> None:
    auth_module, _ = _import_sandbox_auth(monkeypatch)
    singleton = _singleton()
    monkeypatch.setattr(auth_module.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(auth_module.wandb, "run", _run("run-entity", "run-project"))

    assert auth_module._resolve_effective_entity_project() == (
        "run-entity",
        "run-project",
    )


def test_resolve_effective_entity_project_uses_most_recent_active_run(
    monkeypatch,
) -> None:
    auth_module, _ = _import_sandbox_auth(monkeypatch)
    singleton = _singleton(
        most_recent_active_run=_run("recent-entity", "recent-project")
    )
    monkeypatch.setattr(auth_module.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(auth_module.wandb, "run", None)

    assert auth_module._resolve_effective_entity_project() == (
        "recent-entity",
        "recent-project",
    )


def test_override_sandbox_entity_is_noop_for_none(
    monkeypatch,
) -> None:
    auth_module, _ = _import_sandbox_auth(monkeypatch)
    singleton = _singleton(
        most_recent_active_run=_run("recent-entity", "recent-project")
    )
    monkeypatch.setattr(auth_module.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(auth_module.wandb, "run", None)

    with auth_module._override_sandbox_entity(entity=None):
        assert auth_module._resolve_effective_entity_project() == (
            "recent-entity",
            "recent-project",
        )


def test_override_sandbox_entity_overrides_entity_and_suppresses_project(
    monkeypatch,
) -> None:
    auth_module, _ = _import_sandbox_auth(monkeypatch)
    singleton = _singleton(
        most_recent_active_run=_run("recent-entity", "recent-project")
    )
    monkeypatch.setattr(auth_module.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(auth_module.wandb, "run", _run("run-entity", "run-project"))

    with auth_module._override_sandbox_entity(entity="override-entity"):
        assert auth_module._resolve_effective_entity_project() == (
            "override-entity",
            None,
        )

    assert auth_module._resolve_effective_entity_project() == (
        "run-entity",
        "run-project",
    )


def test_resolve_wandb_sdk_auth_uses_session_credentials(
    monkeypatch,
) -> None:
    auth_module, _ = _import_sandbox_auth(monkeypatch)
    singleton = _singleton()
    monkeypatch.setattr(auth_module.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(auth_module.wandb, "run", None)
    auth_module.wbauth.use_explicit_auth(
        auth=auth_module.wbauth.AuthApiKey(
            host="https://api.wandb.ai",
            api_key=_VALID_API_KEY,
        ),
        source="test",
    )
    monkeypatch.setattr(
        auth_module.wandb_login,
        "_login",
        lambda **kwargs: pytest.fail("wandb_login._login should not run"),
    )

    headers = auth_module._resolve_wandb_sdk_auth()

    assert headers.strategy == "wandb_api_key"
    assert headers.headers == {
        "x-api-key": _VALID_API_KEY,
        "x-entity-id": "default-entity",
        "x-project-name": "default-project",
    }


def test_resolve_wandb_sdk_auth_falls_back_to_settings_api_key(
    monkeypatch,
) -> None:
    auth_module, _ = _import_sandbox_auth(monkeypatch)
    singleton = _singleton(api_key=_VALID_API_KEY)
    monkeypatch.setattr(auth_module.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(auth_module.wandb, "run", None)
    monkeypatch.setattr(
        auth_module.wandb_login,
        "_login",
        lambda **kwargs: pytest.fail("wandb_login._login should not run"),
    )

    headers = auth_module._resolve_wandb_sdk_auth()

    assert headers.headers["x-api-key"] == _VALID_API_KEY
    assert headers.headers["x-entity-id"] == "default-entity"
    assert headers.headers["x-project-name"] == "default-project"


def test_resolve_wandb_sdk_auth_loads_auth_when_missing(
    monkeypatch,
) -> None:
    auth_module, _ = _import_sandbox_auth(monkeypatch)
    singleton = _singleton(
        most_recent_active_run=_run("recent-entity", "recent-project")
    )
    login_calls: list[dict[str, object]] = []
    monkeypatch.setattr(auth_module.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(auth_module.wandb, "run", None)

    def fake_login(**kwargs) -> None:
        login_calls.append(kwargs)
        auth_module.wbauth.use_explicit_auth(
            auth=auth_module.wbauth.AuthApiKey(
                host="https://api.wandb.ai",
                api_key=_VALID_API_KEY,
            ),
            source="test",
        )

    monkeypatch.setattr(
        auth_module.wandb_login,
        "_login",
        fake_login,
    )

    headers = auth_module._resolve_wandb_sdk_auth()

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
    auth_module, _ = _import_sandbox_auth(monkeypatch)
    singleton = _singleton(
        entity=None,
        project=None,
        api_key=settings_api_key,
    )
    monkeypatch.setattr(auth_module.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(auth_module.wandb, "run", None)

    if credential_source == "session_credentials":
        auth_module.wbauth.use_explicit_auth(
            auth=auth_module.wbauth.AuthApiKey(
                host="https://api.wandb.ai",
                api_key=_VALID_API_KEY,
            ),
            source="test",
        )

    monkeypatch.setattr(
        auth_module.wandb_login,
        "_login",
        lambda **kwargs: pytest.fail("wandb_login._login should not run"),
    )

    headers = auth_module._resolve_wandb_sdk_auth()

    assert headers.strategy == "wandb_api_key"
    assert headers.headers == {"x-api-key": _VALID_API_KEY}
