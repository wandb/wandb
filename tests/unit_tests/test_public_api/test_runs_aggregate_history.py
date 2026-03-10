"""Tests for Runs.aggregate_history() method."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import polars as pl
import pytest
from wandb.apis.public.runs import Runs, WandbApiFailedError
from wandb.errors import CommError


@dataclass(frozen=True)
class FakeDownloadResult:
    """Mimics wandb.apis.public.runs.DownloadHistoryResult."""

    paths: list[Path]
    contains_live_data: bool = False
    errors: dict | None = None


def _write_parquet(path: Path, data: dict[str, list]) -> Path:
    """Write a dict of columns to a parquet file and return the path."""
    df = pl.DataFrame(data)
    df.write_parquet(path)
    return path


def _make_mock_run_with_parquet(
    run_id: str, history_data: dict[str, list], tmp_dir: Path
) -> mock.MagicMock:
    """Create a mock Run whose download_history_exports writes real parquet.

    Note: parquet does NOT include run_id column -- the new code adds it lazily
    via scan_parquet().with_columns().
    """
    run = mock.MagicMock()
    run.id = run_id

    run_dir_for_export = tmp_dir / f"_export_{run_id}"
    run_dir_for_export.mkdir(parents=True, exist_ok=True)
    parquet_path = run_dir_for_export / "history.parquet"
    _write_parquet(parquet_path, history_data)

    def fake_download(download_dir, require_complete_history=False):
        dest = Path(download_dir) / "history.parquet"
        dest.write_bytes(parquet_path.read_bytes())
        return FakeDownloadResult(paths=[dest], contains_live_data=False)

    run.download_history_exports = mock.MagicMock(side_effect=fake_download)
    return run


def _make_mock_run_with_live_data(
    run_id: str, history_data: dict[str, list], tmp_dir: Path
) -> mock.MagicMock:
    """Create a mock Run whose download returns contains_live_data=True."""
    run = mock.MagicMock()
    run.id = run_id

    run_dir_for_export = tmp_dir / f"_export_{run_id}"
    run_dir_for_export.mkdir(parents=True, exist_ok=True)
    parquet_path = run_dir_for_export / "history.parquet"
    _write_parquet(parquet_path, history_data)

    def fake_download(download_dir, require_complete_history=False):
        dest = Path(download_dir) / "history.parquet"
        dest.write_bytes(parquet_path.read_bytes())
        return FakeDownloadResult(paths=[dest], contains_live_data=True)

    run.download_history_exports = mock.MagicMock(side_effect=fake_download)
    return run


def _make_mock_run_download_fails(
    run_id: str, error_type: Exception | None = None
) -> mock.MagicMock:
    """Create a mock Run whose download_history_exports raises a specific error."""
    run = mock.MagicMock()
    run.id = run_id
    error = error_type or WandbApiFailedError(f"Download failed for {run_id}")
    run.download_history_exports = mock.MagicMock(side_effect=error)
    return run


def _make_mock_runs(mock_run_objects: list[mock.MagicMock]) -> mock.MagicMock:
    """Create a mock Runs object that iterates over the given runs."""
    mock_runs = mock.MagicMock(spec=Runs)
    mock_runs.__iter__ = mock.MagicMock(return_value=iter(mock_run_objects))
    return mock_runs


class TestAggregateHistoryParquetPath:
    def test_returns_lazy_frame(self, tmp_path):
        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0, 1, 2], "loss": [1.0, 0.5, 0.1]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        result = Runs.aggregate_history(runs, cache_dir=str(cache_dir))
        assert isinstance(result, pl.LazyFrame)

    def test_collected_data_matches(self, tmp_path):
        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0, 1, 2], "loss": [1.0, 0.5, 0.1]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(runs, cache_dir=str(cache_dir))
        df = lf.collect()
        assert len(df) == 3
        assert df["loss"].to_list() == [1.0, 0.5, 0.1]

    def test_adds_run_id_column(self, tmp_path):
        run = _make_mock_run_with_parquet(
            "abc123",
            {"_step": [0], "acc": [0.9]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        df = Runs.aggregate_history(runs, cache_dir=str(cache_dir)).collect()
        assert "run_id" in df.columns
        assert df["run_id"].to_list() == ["abc123"]

    def test_multiple_runs(self, tmp_path):
        run1 = _make_mock_run_with_parquet(
            "run1", {"_step": [0, 1], "loss": [1.0, 0.5]}, tmp_path
        )
        run2 = _make_mock_run_with_parquet(
            "run2", {"_step": [0, 1], "loss": [0.8, 0.3]}, tmp_path
        )
        runs = _make_mock_runs([run1, run2])
        cache_dir = tmp_path / "cache"

        df = Runs.aggregate_history(runs, cache_dir=str(cache_dir)).collect()
        assert len(df) == 4
        assert set(df["run_id"].to_list()) == {"run1", "run2"}


class TestAggregateHistoryCaching:
    def test_uses_cached_files(self, tmp_path):
        """If parquet files and .complete sentinel exist in cache, skip download."""
        cache_dir = tmp_path / "cache"
        run_dir = cache_dir / "run1"
        run_dir.mkdir(parents=True)
        _write_parquet(
            run_dir / "cached.parquet",
            {"_step": [0, 1], "loss": [1.0, 0.5], "run_id": ["run1", "run1"]},
        )
        # Write .complete sentinel -- required for cache hit
        (run_dir / ".complete").touch()

        # Run with a mock that should NOT be called for download
        run = mock.MagicMock()
        run.id = "run1"
        runs = _make_mock_runs([run])

        df = Runs.aggregate_history(runs, cache_dir=str(cache_dir)).collect()
        assert len(df) == 2
        # download_history_exports should not have been called
        run.download_history_exports.assert_not_called()


class TestAggregateHistoryKeyFilter:
    def test_filters_to_specified_keys(self, tmp_path):
        run = _make_mock_run_with_parquet(
            "run1",
            {
                "_step": [0, 1],
                "loss": [1.0, 0.5],
                "acc": [0.1, 0.9],
                "lr": [0.01, 0.01],
            },
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(
            runs, cache_dir=str(cache_dir), keys=["loss", "acc"]
        )
        df = lf.collect()
        assert set(df.columns) == {"run_id", "loss", "acc"}

    def test_run_id_always_included(self, tmp_path):
        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0], "loss": [1.0]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(runs, cache_dir=str(cache_dir), keys=["loss"])
        df = lf.collect()
        assert "run_id" in df.columns

    def test_missing_keys_ignored(self, tmp_path):
        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0], "loss": [1.0]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(
            runs, cache_dir=str(cache_dir), keys=["loss", "nonexistent"]
        )
        df = lf.collect()
        assert "nonexistent" not in df.columns
        assert "loss" in df.columns


class TestAggregateHistoryMaxResults:
    def test_limits_total_rows(self, tmp_path):
        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": list(range(100)), "loss": [float(i) for i in range(100)]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        df = Runs.aggregate_history(
            runs, cache_dir=str(cache_dir), max_results=10
        ).collect()
        assert len(df) == 10


class TestAggregateHistoryEmpty:
    def test_no_runs_returns_empty(self, tmp_path):
        runs = _make_mock_runs([])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(runs, cache_dir=str(cache_dir))
        assert isinstance(lf, pl.LazyFrame)
        df = lf.collect()
        assert len(df) == 0

    @mock.patch("wandb.termwarn")
    def test_all_empty_runs(self, mock_termwarn, tmp_path):
        """All runs fail to download -- returns empty LazyFrame with warnings."""
        run1 = _make_mock_run_download_fails("run1")
        run2 = _make_mock_run_download_fails("run2")
        runs = _make_mock_runs([run1, run2])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(runs, cache_dir=str(cache_dir))
        df = lf.collect()
        assert len(df) == 0

    def test_creates_cache_dir(self, tmp_path):
        runs = _make_mock_runs([])
        cache_dir = tmp_path / "new" / "nested" / "cache"
        assert not cache_dir.exists()

        Runs.aggregate_history(runs, cache_dir=str(cache_dir))
        assert cache_dir.exists()


class TestAggregateHistoryDefaultCacheDir:
    """Optional cache_dir with env fallback."""

    @mock.patch("wandb.env.get_cache_dir")
    def test_uses_env_cache_dir_when_no_cache_dir_provided(
        self, mock_get_cache_dir, tmp_path
    ):
        """When no cache_dir argument is given, use env.get_cache_dir() / 'history'."""
        mock_cache_base = tmp_path / "wandb_cache"
        mock_cache_base.mkdir()
        mock_get_cache_dir.return_value = mock_cache_base

        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0, 1], "loss": [1.0, 0.5]},
            tmp_path,
        )
        runs = _make_mock_runs([run])

        lf = Runs.aggregate_history(runs)
        df = lf.collect()

        assert len(df) == 2
        expected_dir = mock_cache_base / "runhistory" / "run1"
        assert expected_dir.exists()
        parquet_files = list(expected_dir.glob("*.parquet"))
        assert len(parquet_files) > 0

    @mock.patch("wandb.env.get_cache_dir")
    def test_explicit_cache_dir_overrides_default(self, mock_get_cache_dir, tmp_path):
        """When explicit cache_dir is provided, use it instead of env default."""
        mock_cache_base = tmp_path / "wandb_cache"
        mock_cache_base.mkdir()
        mock_get_cache_dir.return_value = mock_cache_base

        explicit_dir = tmp_path / "my_explicit_cache"

        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0], "loss": [1.0]},
            tmp_path,
        )
        runs = _make_mock_runs([run])

        lf = Runs.aggregate_history(runs, cache_dir=str(explicit_dir))
        df = lf.collect()

        assert len(df) == 1
        assert (explicit_dir / "run1").exists()
        env_history_dir = mock_cache_base / "runhistory"
        assert not env_history_dir.exists() or not list(
            env_history_dir.glob("**/run1/*.parquet")
        )


class TestAggregateHistorySentinel:
    """Sentinel-based cache validation."""

    def test_sentinel_written_after_successful_download(self, tmp_path):
        """After downloading a run, a .complete sentinel must exist."""
        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0, 1], "loss": [1.0, 0.5]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        Runs.aggregate_history(runs, cache_dir=str(cache_dir)).collect()

        sentinel = cache_dir / "run1" / ".complete"
        assert sentinel.exists(), (
            "Expected .complete sentinel after successful download"
        )

    def test_cached_with_sentinel_skips_download(self, tmp_path):
        """Pre-existing parquet + .complete sentinel = skip download."""
        cache_dir = tmp_path / "cache"
        run_dir = cache_dir / "run1"
        run_dir.mkdir(parents=True)
        _write_parquet(
            run_dir / "history.parquet",
            {"_step": [0, 1], "loss": [1.0, 0.5]},
        )
        (run_dir / ".complete").touch()

        run = mock.MagicMock()
        run.id = "run1"
        runs = _make_mock_runs([run])

        df = Runs.aggregate_history(runs, cache_dir=str(cache_dir)).collect()
        assert len(df) == 2
        run.download_history_exports.assert_not_called()

    def test_parquet_without_sentinel_triggers_redownload(self, tmp_path):
        """Parquet files without .complete sentinel = re-download triggered."""
        cache_dir = tmp_path / "cache"
        run_dir = cache_dir / "run1"
        run_dir.mkdir(parents=True)
        _write_parquet(
            run_dir / "stale.parquet",
            {"_step": [0], "loss": [99.0]},
        )

        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0, 1, 2], "loss": [1.0, 0.5, 0.1]},
            tmp_path,
        )
        runs = _make_mock_runs([run])

        df = Runs.aggregate_history(runs, cache_dir=str(cache_dir)).collect()
        assert len(df) == 3
        run.download_history_exports.assert_called_once()


class TestAggregateHistoryParallelDownloads:
    """Parallel downloads with error isolation."""

    @mock.patch("wandb.termwarn")
    def test_one_failed_run_does_not_abort_others(self, mock_termwarn, tmp_path):
        """Two good runs + one failing run: result has data from good runs only."""
        run1 = _make_mock_run_with_parquet(
            "run1", {"_step": [0, 1], "loss": [1.0, 0.5]}, tmp_path
        )
        run2 = _make_mock_run_with_parquet(
            "run2", {"_step": [0, 1], "loss": [0.8, 0.3]}, tmp_path
        )
        run_fail = _make_mock_run_download_fails("run_fail")
        runs = _make_mock_runs([run1, run2, run_fail])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(runs, cache_dir=str(cache_dir))
        df = lf.collect()

        assert set(df["run_id"].to_list()) == {"run1", "run2"}
        assert len(df) == 4

        termwarn_messages = [str(c) for c in mock_termwarn.call_args_list]
        assert any("run_fail" in msg for msg in termwarn_messages)

    @mock.patch("wandb.termwarn")
    def test_all_runs_fail_returns_empty_lazyframe(self, mock_termwarn, tmp_path):
        """All runs fail download: return empty LazyFrame + termwarn called."""
        run1 = _make_mock_run_download_fails("run1")
        run2 = _make_mock_run_download_fails("run2")
        runs = _make_mock_runs([run1, run2])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(runs, cache_dir=str(cache_dir))
        df = lf.collect()
        assert len(df) == 0
        assert mock_termwarn.called

    def test_max_workers_parameter_accepted(self, tmp_path):
        """aggregate_history accepts max_workers parameter without error."""
        run = _make_mock_run_with_parquet(
            "run1", {"_step": [0], "loss": [1.0]}, tmp_path
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(runs, cache_dir=str(cache_dir), max_workers=2)
        df = lf.collect()
        assert len(df) == 1


class TestAggregateHistoryExceptionNarrowing:
    """Narrowed exception handling."""

    def test_unexpected_exception_propagates(self, tmp_path):
        """RuntimeError from download_history_exports should propagate, not be caught.

        The @normalize_exceptions decorator wraps unexpected exceptions in
        CommError, but the key behavior is that they are NOT silently swallowed
        (as the old ``except Exception: pass`` did).
        """
        run = mock.MagicMock()
        run.id = "run1"
        run.download_history_exports = mock.MagicMock(
            side_effect=RuntimeError("unexpected bug")
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        with pytest.raises((RuntimeError, CommError), match="unexpected bug"):
            Runs.aggregate_history(runs, cache_dir=str(cache_dir)).collect()

    @mock.patch("wandb.termwarn")
    def test_expected_exceptions_caught_gracefully(self, mock_termwarn, tmp_path):
        """OSError from download should be caught gracefully, not propagate."""
        run = _make_mock_run_download_fails("run1", error_type=OSError("disk full"))
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(runs, cache_dir=str(cache_dir))
        df = lf.collect()
        assert len(df) == 0
        assert mock_termwarn.called


class TestAggregateHistoryLiveData:
    """Live data warning."""

    @mock.patch("wandb.termwarn")
    def test_warns_on_live_data(self, mock_termwarn, tmp_path):
        """When contains_live_data=True, termwarn should be called."""
        run = _make_mock_run_with_live_data(
            "run1",
            {"_step": [0, 1], "loss": [1.0, 0.5]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(runs, cache_dir=str(cache_dir))
        df = lf.collect()
        assert len(df) == 2

        termwarn_messages = [str(c) for c in mock_termwarn.call_args_list]
        assert any(
            "not yet exported to parquet" in msg or "incomplete" in msg.lower()
            for msg in termwarn_messages
        ), f"Expected live data warning in termwarn calls: {termwarn_messages}"


class TestAggregateHistoryForceRedownload:
    """Tests for force_redownload parameter."""

    def test_force_redownload_redownloads_cached_run(self, tmp_path):
        """When force_redownload=True, runs with .complete sentinel are re-downloaded."""
        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0, 1], "loss": [1.0, 0.5]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        # First download -- populates cache
        lf = Runs.aggregate_history(runs, cache_dir=str(cache_dir))
        lf.collect()
        assert (cache_dir / "run1" / ".complete").exists()
        assert run.download_history_exports.call_count == 1

        # Second download without force -- should use cache
        runs2 = _make_mock_runs([run])
        lf2 = Runs.aggregate_history(runs2, cache_dir=str(cache_dir))
        lf2.collect()
        assert run.download_history_exports.call_count == 1  # not called again

        # Third download with force -- should re-download
        runs3 = _make_mock_runs([run])
        lf3 = Runs.aggregate_history(
            runs3, cache_dir=str(cache_dir), force_redownload=True
        )
        df3 = lf3.collect()
        assert run.download_history_exports.call_count == 2
        assert len(df3) == 2

    def test_force_redownload_removes_sentinel(self, tmp_path):
        """force_redownload removes the .complete sentinel before re-downloading."""
        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0], "loss": [1.0]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        # First download
        Runs.aggregate_history(runs, cache_dir=str(cache_dir)).collect()
        sentinel = cache_dir / "run1" / ".complete"
        assert sentinel.exists()

        # Force re-download
        runs2 = _make_mock_runs([run])
        Runs.aggregate_history(
            runs2, cache_dir=str(cache_dir), force_redownload=True
        ).collect()
        # Sentinel should be recreated after successful re-download
        assert sentinel.exists()


class TestAggregateHistoryRequireComplete:
    """Tests for require_complete parameter."""

    def test_require_complete_raises_on_live_data(self, tmp_path):
        """When require_complete=True and a run has live data, raise ValueError."""
        run = _make_mock_run_with_live_data(
            "run1",
            {"_step": [0, 1], "loss": [1.0, 0.5]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        with pytest.raises(ValueError, match="not yet exported to parquet"):
            Runs.aggregate_history(
                runs, cache_dir=str(cache_dir), require_complete=True
            ).collect()

    @mock.patch("wandb.termwarn")
    def test_require_complete_false_warns_on_live_data(
        self, mock_termwarn, tmp_path
    ):
        """Default behavior: live data produces warning, not error."""
        run = _make_mock_run_with_live_data(
            "run1",
            {"_step": [0], "loss": [1.0]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(
            runs, cache_dir=str(cache_dir), require_complete=False
        )
        df = lf.collect()
        assert len(df) == 1
        mock_termwarn.assert_called()

    def test_require_complete_no_error_when_all_complete(self, tmp_path):
        """When all runs are complete, require_complete=True succeeds."""
        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0, 1], "loss": [1.0, 0.5]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        lf = Runs.aggregate_history(
            runs, cache_dir=str(cache_dir), require_complete=True
        )
        df = lf.collect()
        assert len(df) == 2
