from __future__ import annotations

import importlib
import sys
import types
from dataclasses import dataclass


def _import_sandbox_auth(monkeypatch):
    cwsandbox_module = types.ModuleType("cwsandbox")
    cwsandbox_module.__path__ = []

    placeholder = type("Placeholder", (), {})
    for name in (
        "NetworkOptions",
        "OperationRef",
        "Process",
        "ProcessResult",
        "RemoteFunction",
        "Sandbox",
        "SandboxDefaults",
        "SandboxStatus",
        "Serialization",
        "Session",
        "StreamReader",
        "StreamWriter",
        "TerminalResult",
        "TerminalSession",
        "Waitable",
    ):
        setattr(cwsandbox_module, name, placeholder)

    cwsandbox_module.results = lambda *args, **kwargs: None
    cwsandbox_module.wait = lambda *args, **kwargs: None
    cwsandbox_module.Secret = type("BaseSecret", (), {})

    @dataclass(frozen=True)
    class AuthHeaders:
        headers: dict[str, str]
        strategy: str

    class CWSandboxAuthenticationError(Exception):
        pass

    registered: dict[str, object | None] = {"name": None, "func": None}

    def set_auth_mode(name: str, func) -> None:
        registered["name"] = name
        registered["func"] = func

    cwsandbox_module.AuthHeaders = AuthHeaders
    cwsandbox_module.CWSandboxAuthenticationError = CWSandboxAuthenticationError
    cwsandbox_module.set_auth_mode = set_auth_mode
    monkeypatch.setitem(sys.modules, "cwsandbox", cwsandbox_module)
    monkeypatch.delitem(sys.modules, "wandb.sandbox", raising=False)
    monkeypatch.delitem(sys.modules, "wandb.sandbox._auth", raising=False)

    auth_module = importlib.import_module("wandb.sandbox._auth")
    return auth_module, registered


def test_private_override_sandbox_entity_overrides_entity_without_leaking_project(
    monkeypatch,
) -> None:
    auth_module, registered = _import_sandbox_auth(monkeypatch)

    singleton = types.SimpleNamespace(
        settings=types.SimpleNamespace(
            entity="default-entity",
            project="default-project",
            api_key=None,
            base_url="https://api.wandb.ai",
            app_url="https://wandb.ai",
        ),
        most_recent_active_run=None,
    )
    monkeypatch.setattr(auth_module.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(auth_module.wandb, "run", None)

    assert registered["name"] == auth_module._AUTH_MODE_NAME
    assert registered["func"] is auth_module._resolve_wandb_sdk_auth
    assert not hasattr(auth_module, "override_auth_context")
    assert not hasattr(auth_module, "override_sandbox_entity")
    assert not hasattr(auth_module, "register_wandb_auth_mode")
    assert auth_module._resolve_effective_entity_project() == (
        "default-entity",
        "default-project",
    )


def test_private_override_sandbox_entity_is_noop_for_none(monkeypatch) -> None:
    auth_module, _ = _import_sandbox_auth(monkeypatch)

    singleton = types.SimpleNamespace(
        settings=types.SimpleNamespace(
            entity="default-entity",
            project="default-project",
            api_key=None,
            base_url="https://api.wandb.ai",
            app_url="https://wandb.ai",
        ),
        most_recent_active_run=None,
    )
    monkeypatch.setattr(auth_module.wandb_setup, "singleton", lambda: singleton)
    monkeypatch.setattr(auth_module.wandb, "run", None)

    with auth_module._override_sandbox_entity(entity=None):
        assert auth_module._resolve_effective_entity_project() == (
            "default-entity",
            "default-project",
        )

    with auth_module._override_sandbox_entity(entity="non-default-entity"):
        assert auth_module._resolve_effective_entity_project() == (
            "non-default-entity",
            None,
        )

    assert auth_module._resolve_effective_entity_project() == (
        "default-entity",
        "default-project",
    )
