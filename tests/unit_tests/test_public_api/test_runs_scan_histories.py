"""Tests for Runs.scan_histories() method."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import polars as pl
from wandb.apis.public.runs import Runs


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
    """Create a mock Run whose download_history_exports writes real parquet."""
    run = mock.MagicMock()
    run.id = run_id

    run_dir_for_export = tmp_dir / f"_export_{run_id}"
    run_dir_for_export.mkdir(parents=True, exist_ok=True)
    parquet_path = run_dir_for_export / "history.parquet"
    _write_parquet(parquet_path, history_data)

    def fake_download(download_dir, require_complete_history=False):
        # Copy parquet to the download_dir (simulating what wandb-core does)
        dest = Path(download_dir) / "history.parquet"
        dest.write_bytes(parquet_path.read_bytes())
        return FakeDownloadResult(paths=[dest])

    run.download_history_exports = mock.MagicMock(side_effect=fake_download)
    run.scan_history = mock.MagicMock(return_value=iter([]))
    return run


def _make_mock_run_graphql_fallback(
    run_id: str, history_rows: list[dict]
) -> mock.MagicMock:
    """Create a mock Run where parquet export fails, falls back to GraphQL."""
    run = mock.MagicMock()
    run.id = run_id
    run.download_history_exports = mock.MagicMock(
        side_effect=Exception("No parquet available")
    )
    run.scan_history = mock.MagicMock(return_value=iter(history_rows))
    return run


def _make_mock_run_empty(run_id: str) -> mock.MagicMock:
    """Create a mock Run with no history data at all."""
    run = mock.MagicMock()
    run.id = run_id
    run.download_history_exports = mock.MagicMock(
        side_effect=Exception("No parquet available")
    )
    run.scan_history = mock.MagicMock(return_value=iter([]))
    return run


def _make_mock_runs(mock_run_objects: list[mock.MagicMock]) -> mock.MagicMock:
    """Create a mock Runs object that iterates over the given runs."""
    mock_runs = mock.MagicMock(spec=Runs)
    mock_runs.__iter__ = mock.MagicMock(return_value=iter(mock_run_objects))
    return mock_runs


class TestScanHistoriesParquetPath:
    def test_returns_lazy_frame(self, tmp_path):
        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0, 1, 2], "loss": [1.0, 0.5, 0.1]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        result = Runs.scan_histories(runs, cache_dir=str(cache_dir))
        assert isinstance(result, pl.LazyFrame)

    def test_collected_data_matches(self, tmp_path):
        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": [0, 1, 2], "loss": [1.0, 0.5, 0.1]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        lf = Runs.scan_histories(runs, cache_dir=str(cache_dir))
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

        df = Runs.scan_histories(runs, cache_dir=str(cache_dir)).collect()
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

        df = Runs.scan_histories(runs, cache_dir=str(cache_dir)).collect()
        assert len(df) == 4
        assert set(df["run_id"].to_list()) == {"run1", "run2"}


class TestScanHistoriesGraphQLFallback:
    def test_falls_back_to_scan_history(self, tmp_path):
        run = _make_mock_run_graphql_fallback(
            "run1",
            [
                {"_step": 0, "loss": 1.0},
                {"_step": 1, "loss": 0.5},
            ],
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        df = Runs.scan_histories(runs, cache_dir=str(cache_dir)).collect()
        assert len(df) == 2
        assert df["run_id"].to_list() == ["run1", "run1"]

    def test_writes_fallback_parquet(self, tmp_path):
        run = _make_mock_run_graphql_fallback(
            "run1",
            [{"_step": 0, "loss": 1.0}],
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        Runs.scan_histories(runs, cache_dir=str(cache_dir)).collect()

        fallback_file = cache_dir / "run1" / "history_fallback.parquet"
        assert fallback_file.exists()


class TestScanHistoriesCaching:
    def test_uses_cached_files(self, tmp_path):
        """If parquet files already exist in cache, skip download."""
        cache_dir = tmp_path / "cache"
        run_dir = cache_dir / "run1"
        run_dir.mkdir(parents=True)
        _write_parquet(
            run_dir / "cached.parquet",
            {"_step": [0, 1], "loss": [1.0, 0.5], "run_id": ["run1", "run1"]},
        )

        # Run with a mock that should NOT be called for download
        run = mock.MagicMock()
        run.id = "run1"
        runs = _make_mock_runs([run])

        df = Runs.scan_histories(runs, cache_dir=str(cache_dir)).collect()
        assert len(df) == 2
        # download_history_exports should not have been called
        run.download_history_exports.assert_not_called()


class TestScanHistoriesKeyFilter:
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

        lf = Runs.scan_histories(runs, cache_dir=str(cache_dir), keys=["loss", "acc"])
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

        lf = Runs.scan_histories(runs, cache_dir=str(cache_dir), keys=["loss"])
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

        lf = Runs.scan_histories(
            runs, cache_dir=str(cache_dir), keys=["loss", "nonexistent"]
        )
        df = lf.collect()
        assert "nonexistent" not in df.columns
        assert "loss" in df.columns


class TestScanHistoriesMaxResults:
    def test_limits_total_rows(self, tmp_path):
        run = _make_mock_run_with_parquet(
            "run1",
            {"_step": list(range(100)), "loss": [float(i) for i in range(100)]},
            tmp_path,
        )
        runs = _make_mock_runs([run])
        cache_dir = tmp_path / "cache"

        df = Runs.scan_histories(
            runs, cache_dir=str(cache_dir), max_results=10
        ).collect()
        assert len(df) == 10


class TestScanHistoriesEmpty:
    def test_no_runs_returns_empty(self, tmp_path):
        runs = _make_mock_runs([])
        cache_dir = tmp_path / "cache"

        lf = Runs.scan_histories(runs, cache_dir=str(cache_dir))
        assert isinstance(lf, pl.LazyFrame)
        df = lf.collect()
        assert len(df) == 0

    def test_all_empty_runs(self, tmp_path):
        run1 = _make_mock_run_empty("run1")
        run2 = _make_mock_run_empty("run2")
        runs = _make_mock_runs([run1, run2])
        cache_dir = tmp_path / "cache"

        lf = Runs.scan_histories(runs, cache_dir=str(cache_dir))
        df = lf.collect()
        assert len(df) == 0

    def test_creates_cache_dir(self, tmp_path):
        runs = _make_mock_runs([])
        cache_dir = tmp_path / "new" / "nested" / "cache"
        assert not cache_dir.exists()

        Runs.scan_histories(runs, cache_dir=str(cache_dir))
        assert cache_dir.exists()
