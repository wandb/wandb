"""Tests for wandb.integration.aviato.SandboxSession."""

from __future__ import annotations

import sys
import threading
import types
from dataclasses import dataclass, field, replace
from typing import Any
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Fake aviato module — mirrors Session / SandboxDefaults / Sandbox just enough
# for the integration to work without installing aviato.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeSandboxDefaults:
    environment_variables: dict[str, str] = field(default_factory=dict)
    tags: tuple[str, ...] = field(default_factory=tuple)

    def with_overrides(self, **kwargs: Any) -> _FakeSandboxDefaults:
        return replace(self, **kwargs)

    def merge_environment_variables(
        self, additional: dict[str, str] | None
    ) -> dict[str, str]:
        merged = dict(self.environment_variables)
        if additional:
            merged.update(additional)
        return merged

    def merge_tags(self, additional: list[str] | None) -> list[str]:
        base = list(self.tags)
        if additional:
            base.extend(additional)
        return base


class _FakeSandbox:
    def __init__(self, sandbox_id: str | None = None, **kwargs: Any) -> None:
        self.sandbox_id = sandbox_id

    async def _start_async(self) -> str:
        self.sandbox_id = self.sandbox_id or "sb-fake"
        return self.sandbox_id


class _FakeSession:
    def __init__(
        self,
        defaults: _FakeSandboxDefaults | None = None,
        report_to: list[str] | None = None,
    ) -> None:
        self._defaults = defaults or _FakeSandboxDefaults()
        self._sandboxes: dict[int, _FakeSandbox] = {}
        self._closed = False

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    def sandbox(self, **kwargs: Any) -> _FakeSandbox:
        sb = _FakeSandbox(**kwargs)
        self._sandboxes[id(sb)] = sb
        return sb


def _make_fake_aviato_module() -> types.ModuleType:
    mod = types.ModuleType("aviato")
    mod.Session = _FakeSession  # type: ignore[attr-defined]
    mod.SandboxDefaults = _FakeSandboxDefaults  # type: ignore[attr-defined]
    mod.Sandbox = _FakeSandbox  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _inject_fake_aviato(monkeypatch: pytest.MonkeyPatch):
    """Inject fake aviato into sys.modules for every test."""
    fake = _make_fake_aviato_module()
    monkeypatch.setitem(sys.modules, "aviato", fake)
    # Also clear cached imports of our module so it re-imports with the fake
    for key in list(sys.modules):
        if key.startswith("wandb.integration.aviato"):
            monkeypatch.delitem(sys.modules, key, raising=False)


@pytest.fixture()
def mock_run(monkeypatch: pytest.MonkeyPatch) -> mock.Mock:
    run = mock.Mock()
    run.id = "abc123"
    run.name = "crimson-sunset-42"
    run._settings.api_key = "test-api-key"
    run.entity = "test-entity"
    run.project = "test-project"
    run._settings.base_url = "https://api.wandb.ai"
    monkeypatch.setattr("wandb.run", run)
    return run


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _join_log_threads(timeout: float = 1.0) -> None:
    """Wait for any daemon threads spawned by sandbox start hooks."""
    for t in threading.enumerate():
        if t.daemon and t.name.startswith("Thread"):
            t.join(timeout)


# ---------------------------------------------------------------------------
# Environment variable injection
# ---------------------------------------------------------------------------


def test_injects_wandb_env_vars(mock_run: mock.Mock):
    from wandb.integration.aviato.session import SandboxSession

    session = SandboxSession()

    assert session._defaults.environment_variables["WANDB_API_KEY"] == "test-api-key"
    assert session._defaults.environment_variables["WANDB_ENTITY"] == "test-entity"
    assert session._defaults.environment_variables["WANDB_PROJECT"] == "test-project"
    assert "WANDB_BASE_URL" not in session._defaults.environment_variables


def test_no_run_no_injection(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("wandb.run", None)

    from wandb.integration.aviato.session import SandboxSession

    session = SandboxSession()

    assert session._defaults.environment_variables == {}


def test_user_env_vars_take_precedence(mock_run: mock.Mock):
    from wandb.integration.aviato.session import SandboxSession

    user_defaults = _FakeSandboxDefaults(
        environment_variables={"WANDB_PROJECT": "user-override", "MY_VAR": "hello"}
    )
    session = SandboxSession(defaults=user_defaults)

    assert session._defaults.environment_variables["WANDB_PROJECT"] == "user-override"
    assert session._defaults.environment_variables["MY_VAR"] == "hello"
    assert session._defaults.environment_variables["WANDB_API_KEY"] == "test-api-key"


def test_base_url_injected_for_non_default(mock_run: mock.Mock):
    mock_run._settings.base_url = "https://custom.wandb.ai"

    from wandb.integration.aviato.session import SandboxSession

    session = SandboxSession()

    assert (
        session._defaults.environment_variables["WANDB_BASE_URL"]
        == "https://custom.wandb.ai"
    )


# ---------------------------------------------------------------------------
# Session enter — run name tagging
# ---------------------------------------------------------------------------


def test_enter_tags_with_run_name(mock_run: mock.Mock):
    from wandb.integration.aviato.session import SandboxSession

    session = SandboxSession()
    session.__enter__()

    assert "wandb-crimson-sunset-42" in session._defaults.tags


def test_enter_preserves_existing_tags(mock_run: mock.Mock):
    from wandb.integration.aviato.session import SandboxSession

    session = SandboxSession(defaults=_FakeSandboxDefaults(tags=("my-app", "prod")))
    session.__enter__()

    assert "my-app" in session._defaults.tags
    assert "prod" in session._defaults.tags
    assert "wandb-crimson-sunset-42" in session._defaults.tags


def test_enter_no_run_no_tag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("wandb.run", None)

    from wandb.integration.aviato.session import SandboxSession

    session = SandboxSession()
    session.__enter__()

    assert session._defaults.tags == ()


def test_enter_no_duplicate_tag(mock_run: mock.Mock):
    from wandb.integration.aviato.session import SandboxSession

    session = SandboxSession(
        defaults=_FakeSandboxDefaults(tags=("wandb-crimson-sunset-42",))
    )
    session.__enter__()

    assert session._defaults.tags.count("wandb-crimson-sunset-42") == 1


def test_enter_skips_invalid_k8s_name(mock_run: mock.Mock):
    mock_run.name = "!!!totally invalid!!!"

    from wandb.integration.aviato.session import SandboxSession

    session = SandboxSession()
    session.__enter__()

    assert session._defaults.tags == ()


@pytest.mark.asyncio
async def test_aenter_tags_with_run_name(mock_run: mock.Mock):
    from wandb.integration.aviato.session import SandboxSession

    session = SandboxSession()
    await session.__aenter__()

    assert "wandb-crimson-sunset-42" in session._defaults.tags


# ---------------------------------------------------------------------------
# Sandbox start — log sandbox ID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sandbox_start_logs_id(mock_run: mock.Mock):
    from wandb.integration.aviato.session import SandboxSession

    session = SandboxSession()
    sb = session.sandbox(sandbox_id="sb-999")
    sandbox_id = await sb._start_async()

    assert sandbox_id == "sb-999"
    _join_log_threads()
    mock_run.log.assert_called_once_with({"aviato/sandbox_id": "sb-999"})


@pytest.mark.asyncio
async def test_sandbox_start_no_run_no_log(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("wandb.run", None)

    from wandb.integration.aviato.session import SandboxSession

    session = SandboxSession()
    sb = session.sandbox(sandbox_id="sb-999")
    sandbox_id = await sb._start_async()

    _join_log_threads()
    assert sandbox_id == "sb-999"


@pytest.mark.asyncio
async def test_sandbox_start_log_failure_no_propagate(mock_run: mock.Mock):
    mock_run.log.side_effect = RuntimeError("wandb down")

    from wandb.integration.aviato.session import SandboxSession

    session = SandboxSession()
    sb = session.sandbox(sandbox_id="sb-999")
    sandbox_id = await sb._start_async()

    _join_log_threads()
    assert sandbox_id == "sb-999"


# ---------------------------------------------------------------------------
# run.SandboxSession property
# ---------------------------------------------------------------------------


def test_run_sandbox_session_property(mock_run: mock.Mock):
    from wandb.integration.aviato.session import SandboxSession

    # Simulate what the property does
    assert SandboxSession is not None
    assert issubclass(SandboxSession, _FakeSession)
