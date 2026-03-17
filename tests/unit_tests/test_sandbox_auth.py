from __future__ import annotations

import pytest

pytest.importorskip("cwsandbox")

from wandb.sandbox import _auth as sandbox_auth
from wandb.sdk import wandb_login, wandb_setup
from wandb.sdk.lib import wbauth


@pytest.fixture(autouse=True)
def clear_session_auth() -> None:
    wbauth.unauthenticate_session()
    yield
    wbauth.unauthenticate_session()


@pytest.mark.usefixtures("local_settings")
def test_resolve_auth_context_uses_configured_base_url_for_session_auth(
    dummy_api_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qa_url = "https://api.qa.wandb.ai"
    settings = wandb_setup.singleton().settings
    settings.base_url = qa_url
    settings.entity = "qa-entity"
    settings.project = "qa-project"
    monkeypatch.setattr(sandbox_auth, "_current_run", lambda: None)

    wbauth.use_explicit_auth(
        wbauth.AuthApiKey(api_key=dummy_api_key, host=qa_url),
        source="test",
    )

    context = sandbox_auth.resolve_auth_context()

    assert context.strategy == "wandb_api_key"
    assert context.entity == "qa-entity"
    assert context.project == "qa-project"
    assert context.metadata == (
        ("x-api-key", dummy_api_key),
        ("x-entity-id", "qa-entity"),
        ("x-project-name", "qa-project"),
    )


@pytest.mark.usefixtures("local_settings")
def test_resolve_auth_context_uses_configured_base_url_for_lazy_login(
    dummy_api_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qa_url = "https://api.qa.wandb.ai"
    settings = wandb_setup.singleton().settings
    settings.base_url = qa_url
    settings.api_key = None
    settings.entity = None
    settings.project = None
    monkeypatch.setattr(sandbox_auth, "_current_run", lambda: None)

    login_calls: dict[str, object] = {}

    def fake_login(
        *, host: str, update_api_key: bool, _silent: bool
    ) -> tuple[bool, str]:
        login_calls["host"] = host
        login_calls["update_api_key"] = update_api_key
        login_calls["silent"] = _silent
        wbauth.use_explicit_auth(
            wbauth.AuthApiKey(api_key=dummy_api_key, host=host),
            source="test",
        )
        return True, dummy_api_key

    monkeypatch.setattr(wandb_login, "_login", fake_login)

    context = sandbox_auth.resolve_auth_context()

    assert login_calls == {
        "host": qa_url,
        "update_api_key": False,
        "silent": False,
    }
    assert context.strategy == "wandb_api_key"
    assert context.metadata == (("x-api-key", dummy_api_key),)
