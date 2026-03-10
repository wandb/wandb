"""Tests for wandb.integration.aviato — Session, SandboxDefaults, Sandbox monkeypatch."""

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
    def __init__(self, sandbox_id: str | None = None) -> None:
        self.sandbox_id = sandbox_id

    async def _start_async(self) -> str:
        self.sandbox_id = self.sandbox_id or "sb-fake"
        return self.sandbox_id


class _FakeSession:
    def __init__(
        self,
        defaults: _FakeSandboxDefaults | None = None,
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
def _clean_aviato(monkeypatch: pytest.MonkeyPatch):
    """Inject fake aviato into sys.modules and clean up after each test."""
    # Save true originals before any patching
    orig_enter = _FakeSession.__enter__
    orig_exit = _FakeSession.__exit__
    orig_aenter = _FakeSession.__aenter__
    orig_aexit = _FakeSession.__aexit__
    orig_merge = _FakeSandboxDefaults.merge_environment_variables
    orig_start = _FakeSandbox._start_async

    fake = _make_fake_aviato_module()
    monkeypatch.setitem(sys.modules, "aviato", fake)
    yield
    # Restore true originals — prevents wrapping accumulation across tests
    _FakeSession.__enter__ = orig_enter  # type: ignore[assignment]
    _FakeSession.__exit__ = orig_exit  # type: ignore[assignment]
    _FakeSession.__aenter__ = orig_aenter  # type: ignore[assignment]
    _FakeSession.__aexit__ = orig_aexit  # type: ignore[assignment]
    _FakeSandboxDefaults.merge_environment_variables = orig_merge  # type: ignore[assignment]
    _FakeSandbox._start_async = orig_start  # type: ignore[assignment]
    for cls in (_FakeSession, _FakeSandboxDefaults, _FakeSandbox):
        for attr in list(vars(cls)):
            if attr.startswith("_wandb_"):
                delattr(cls, attr)


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
# patch / unpatch
# ---------------------------------------------------------------------------


def test_patch_sets_flag():
    from wandb.integration.aviato import patch

    patch()

    assert getattr(_FakeSession, "_wandb_patched", False) is True


def test_patch_is_idempotent():
    from wandb.integration.aviato import patch

    patch()
    enter_after_first = _FakeSession.__enter__

    patch()  # second call — no-op
    assert _FakeSession.__enter__ is enter_after_first


def test_unpatch_restores_originals():
    original_enter = _FakeSession.__enter__
    original_merge = _FakeSandboxDefaults.merge_environment_variables
    original_start = _FakeSandbox._start_async

    from wandb.integration.aviato import patch, unpatch

    patch()
    unpatch()

    assert _FakeSession.__enter__ is original_enter
    assert _FakeSandboxDefaults.merge_environment_variables is original_merge
    assert _FakeSandbox._start_async is original_start
    assert not hasattr(_FakeSession, "_wandb_patched")


def test_unpatch_noop_when_not_patched():
    from wandb.integration.aviato import unpatch

    unpatch()  # should not raise


# ---------------------------------------------------------------------------
# 1. Environment variable injection (merge_environment_variables)
# ---------------------------------------------------------------------------


def test_merge_env_injects_wandb_vars(mock_run: mock.Mock):
    from wandb.integration.aviato import patch

    patch()

    defaults = _FakeSandboxDefaults()
    merged = defaults.merge_environment_variables(None)

    assert merged["WANDB_API_KEY"] == "test-api-key"
    assert merged["WANDB_ENTITY"] == "test-entity"
    assert merged["WANDB_PROJECT"] == "test-project"
    assert "WANDB_BASE_URL" not in merged  # default URL excluded


def test_merge_env_no_run(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("wandb.run", None)

    from wandb.integration.aviato import patch

    patch()

    defaults = _FakeSandboxDefaults()
    merged = defaults.merge_environment_variables(None)

    assert merged == {}


def test_merge_env_user_vars_win(mock_run: mock.Mock):
    from wandb.integration.aviato import patch

    patch()

    defaults = _FakeSandboxDefaults(
        environment_variables={"WANDB_PROJECT": "user-override"}
    )
    merged = defaults.merge_environment_variables(None)

    assert merged["WANDB_PROJECT"] == "user-override"  # user wins
    assert merged["WANDB_API_KEY"] == "test-api-key"  # injected


def test_merge_env_additional_vars_win(mock_run: mock.Mock):
    from wandb.integration.aviato import patch

    patch()

    defaults = _FakeSandboxDefaults()
    merged = defaults.merge_environment_variables(
        {"WANDB_ENTITY": "sandbox-override", "MY_VAR": "hello"}
    )

    assert merged["WANDB_ENTITY"] == "sandbox-override"  # additional wins
    assert merged["MY_VAR"] == "hello"  # preserved
    assert merged["WANDB_API_KEY"] == "test-api-key"  # injected


def test_merge_env_base_url_injected_for_non_default(mock_run: mock.Mock):
    mock_run._settings.base_url = "https://custom.wandb.ai"

    from wandb.integration.aviato import patch

    patch()

    defaults = _FakeSandboxDefaults()
    merged = defaults.merge_environment_variables(None)

    assert merged["WANDB_BASE_URL"] == "https://custom.wandb.ai"


# ---------------------------------------------------------------------------
# 2. Session.__enter__ — run ID tagging
# ---------------------------------------------------------------------------


def test_enter_tags_with_run_id(mock_run: mock.Mock):
    from wandb.integration.aviato import patch

    patch()

    session = _FakeSession()
    session.__enter__()

    assert "wandb-crimson-sunset-42" in session._defaults.tags


def test_enter_preserves_existing_tags(mock_run: mock.Mock):
    from wandb.integration.aviato import patch

    patch()

    session = _FakeSession(defaults=_FakeSandboxDefaults(tags=("my-app", "prod")))
    session.__enter__()

    assert "my-app" in session._defaults.tags
    assert "prod" in session._defaults.tags
    assert "wandb-crimson-sunset-42" in session._defaults.tags


def test_enter_no_run_no_tag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("wandb.run", None)

    from wandb.integration.aviato import patch

    patch()

    session = _FakeSession()
    session.__enter__()

    assert session._defaults.tags == ()


def test_enter_skips_tag_for_invalid_k8s_name(mock_run: mock.Mock):
    mock_run.name = "!!!totally invalid!!!"

    from wandb.integration.aviato import patch

    patch()

    session = _FakeSession()
    session.__enter__()

    # Tag is rejected (not mangled) — no wandb tag added
    assert session._defaults.tags == ()


def test_enter_no_duplicate_tag(mock_run: mock.Mock):
    from wandb.integration.aviato import patch

    patch()

    session = _FakeSession(
        defaults=_FakeSandboxDefaults(tags=("wandb-crimson-sunset-42",))
    )
    session.__enter__()

    assert session._defaults.tags.count("wandb-crimson-sunset-42") == 1


# ---------------------------------------------------------------------------
# 3. Sandbox._start_async — log sandbox ID immediately
# ---------------------------------------------------------------------------


def _join_log_threads(timeout: float = 1.0) -> None:
    """Wait for any daemon threads spawned by _patched_start to finish."""
    for t in threading.enumerate():
        if t.daemon and t.name.startswith("Thread"):
            t.join(timeout)


@pytest.mark.asyncio
async def test_start_logs_sandbox_id(mock_run: mock.Mock):
    from wandb.integration.aviato import patch

    patch()

    sb = _FakeSandbox(sandbox_id="sb-999")
    sandbox_id = await sb._start_async()

    assert sandbox_id == "sb-999"
    _join_log_threads()
    mock_run.log.assert_called_once_with({"aviato/sandbox_id": "sb-999"})


@pytest.mark.asyncio
async def test_start_no_run_no_log(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("wandb.run", None)

    from wandb.integration.aviato import patch

    patch()

    sb = _FakeSandbox(sandbox_id="sb-999")
    sandbox_id = await sb._start_async()

    _join_log_threads()
    assert sandbox_id == "sb-999"  # original still works


@pytest.mark.asyncio
async def test_start_log_failure_does_not_propagate(mock_run: mock.Mock):
    mock_run.log.side_effect = RuntimeError("wandb down")

    from wandb.integration.aviato import patch

    patch()

    sb = _FakeSandbox(sandbox_id="sb-999")
    sandbox_id = await sb._start_async()

    _join_log_threads()
    assert sandbox_id == "sb-999"  # sandbox start not affected


# ---------------------------------------------------------------------------
# Async enter path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aenter_tags_with_run_id(mock_run: mock.Mock):
    from wandb.integration.aviato import patch

    patch()

    session = _FakeSession()
    await session.__aenter__()

    assert "wandb-crimson-sunset-42" in session._defaults.tags


# ---------------------------------------------------------------------------
# setup()
# ---------------------------------------------------------------------------


def test_setup_patches_when_aviato_imported():
    from wandb.integration.aviato import setup

    setup()

    assert getattr(_FakeSession, "_wandb_patched", False) is True


def test_setup_registers_import_hook_when_aviato_not_imported(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delitem(sys.modules, "aviato")

    with mock.patch("wandb.util.add_import_hook") as mock_add_hook:
        from wandb.integration.aviato import setup

        setup()

        mock_add_hook.assert_called_once()
        assert mock_add_hook.call_args[0][0] == "aviato"
