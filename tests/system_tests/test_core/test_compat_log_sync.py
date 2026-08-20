from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from wandb.cli import cli

from tests.fixtures.wandb_backend_spy import WandbBackendSpy
from tests.fixtures.wandb_backend_spy.resume_stubs import stub_resume_for_sync

STEP_FIXTURES: tuple[tuple[str, set[int]], ...] = (
    ("old_auto_steps", {0, 1, 2}),
    ("old_auto_steps_flat_keys", {0, 1, 2}),
    ("old_explicit_steps", {0, 5, 10}),
    ("old_resumed_run", {5, 6, 7}),
)

SHARED_MODE_FIXTURES = ("old_shared_mode", "new_shared_mode")


def _invoke_sync(
    runner: CliRunner,
    run_dir: Path,
    *,
    legacy: bool,
) -> Any:
    args = [str(run_dir)]
    if legacy:
        args.append("--legacy")
    return runner.invoke(cli.sync, args)


def _history_steps(snapshot: Any, *, run_id: str) -> set[int]:
    history = snapshot.history(run_id=run_id)
    return {row["_step"] for row in history.values()}


@pytest.mark.parametrize("legacy", (False, True))
@pytest.mark.parametrize(
    ("fixture", "expected_steps"),
    STEP_FIXTURES,
    ids=[case[0] for case in STEP_FIXTURES],
)
def test_sync_compat_log_uploads_expected_steps(
    wandb_backend_spy: WandbBackendSpy,
    runner: CliRunner,
    copy_asset: Callable[[str], Path],
    legacy: bool,
    fixture: str,
    expected_steps: set[int],
):
    """Sync a pinned golden fixture and assert uploaded history steps."""
    run_dir = copy_asset(f"compat_logs/offline-run-{fixture}")

    result = _invoke_sync(runner, run_dir, legacy=legacy)
    assert result.exit_code == 0

    with wandb_backend_spy.freeze() as snapshot:
        assert _history_steps(snapshot, run_id=fixture) == expected_steps


@pytest.mark.parametrize("legacy", (False, True))
def test_sync_compat_log_no_history_syncs_cleanly(
    wandb_backend_spy: WandbBackendSpy,
    runner: CliRunner,
    copy_asset: Callable[[str], Path],
    legacy: bool,
):
    run_dir = copy_asset("compat_logs/offline-run-old_no_history")

    result = _invoke_sync(runner, run_dir, legacy=legacy)
    assert result.exit_code == 0

    with wandb_backend_spy.freeze() as snapshot:
        assert snapshot.history(run_id="old_no_history") == {}


@pytest.mark.parametrize(
    "legacy",
    (
        False,
        pytest.param(
            True,
            marks=pytest.mark.skip(
                reason=(
                    "TODO: legacy sync crashes in _ensure_history_step when "
                    "replaying unparseable _step values (str vs int comparison)"
                ),
            ),
        ),
    ),
)
def test_sync_compat_log_bad_step_types_renumbers_unparseable_steps(
    wandb_backend_spy: WandbBackendSpy,
    runner: CliRunner,
    copy_asset: Callable[[str], Path],
    legacy: bool,
):
    run_dir = copy_asset("compat_logs/offline-run-old_bad_step_types")

    result = _invoke_sync(runner, run_dir, legacy=legacy)
    assert result.exit_code == 0

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id="old_bad_step_types")
        assert len(history) == 6
        assert _history_steps(snapshot, run_id="old_bad_step_types") == {
            0,
            1,
            2,
            3,
            4,
            5,
        }
        for row in history.values():
            assert list(row.keys()).count("_step") == 1


def test_sync_compat_log_resume_mode_rebases_from_server_step(
    wandb_backend_spy: WandbBackendSpy,
    runner: CliRunner,
    copy_asset: Callable[[str], Path],
    user: str,
):
    """Beta sync honors resume_mode recorded in the transaction log."""
    fixture = "new_resume_mode"
    run_dir = copy_asset(f"compat_logs/offline-run-{fixture}")
    stub_resume_for_sync(
        wandb_backend_spy,
        run_id=fixture,
        last_step=4,
        entity=user,
    )

    result = _invoke_sync(runner, run_dir, legacy=False)
    assert result.exit_code == 0

    with wandb_backend_spy.freeze() as snapshot:
        assert _history_steps(snapshot, run_id=fixture) == {5, 6, 7}

# FIXME:
# FIXME: remove 'new' file case when shared mode is persisted on compat-log RunRecords
# FIXME:
@pytest.mark.parametrize("fixture", SHARED_MODE_FIXTURES)
@pytest.mark.parametrize("legacy", (False, True))
def test_sync_compat_log_non_shared_invents_step_axis(
    wandb_backend_spy: WandbBackendSpy,
    runner: CliRunner,
    copy_asset: Callable[[str], Path],
    fixture: str,
    legacy: bool,
):
    """Without shared mode, history uploads include an invented step axis."""
    run_dir = copy_asset(f"compat_logs/offline-run-{fixture}")

    result = _invoke_sync(runner, run_dir, legacy=legacy)
    assert result.exit_code == 0

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=fixture)
        assert history
        assert _history_steps(snapshot, run_id=fixture) == {0, 1}


# FIXME:
# FIXME: remove 'skip' when shared mode is persisted on compat-log RunRecords
# FIXME:
@pytest.mark.parametrize("fixture", SHARED_MODE_FIXTURES)
@pytest.mark.skip(
    reason=(
        "shared mode is not yet persisted on compat-log RunRecords; "
        "see tests/assets/compat_logs/README.md"
    )
)
def test_sync_compat_log_shared_mode_omits_step_axis(
    wandb_backend_spy: WandbBackendSpy,
    runner: CliRunner,
    copy_asset: Callable[[str], Path],
    fixture: str,
):
    run_dir = copy_asset(f"compat_logs/offline-run-{fixture}")

    result = _invoke_sync(runner, run_dir, legacy=False)
    assert result.exit_code == 0

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=fixture)
        assert history
        for row in history.values():
            assert "_step" not in row
