"""Tests for Runs.summary_metrics() method."""

from __future__ import annotations

from unittest import mock

import pandas as pd
import polars as pl
import pytest
from wandb.apis.public.runs import Runs


def _make_mock_run(run_id: str, summary: dict | None = None):
    """Create a mock Run with the given id and summary_metrics."""
    run = mock.MagicMock()
    run.id = run_id
    run.summary_metrics = summary if summary is not None else {}
    return run


def _make_mock_runs(run_specs: list[tuple[str, dict | None]]):
    """Create a mock Runs object that iterates over mock runs.

    Args:
        run_specs: List of (run_id, summary_metrics) tuples.
    """
    mock_runs = mock.MagicMock(spec=Runs)
    mock_run_objects = [_make_mock_run(rid, sm) for rid, sm in run_specs]
    mock_runs.__iter__ = mock.MagicMock(return_value=iter(mock_run_objects))
    mock_runs.objects = mock_run_objects
    return mock_runs


class TestSummaryMetricsDefaultFormat:
    def test_returns_list_of_dicts(self):
        runs = _make_mock_runs(
            [
                ("run1", {"loss": 0.5, "accuracy": 0.9}),
                ("run2", {"loss": 0.3, "accuracy": 0.95}),
            ]
        )
        result = Runs.summary_metrics(runs, format="default")
        assert isinstance(result, list)
        assert len(result) == 2

    def test_includes_run_id(self):
        runs = _make_mock_runs(
            [
                ("run1", {"loss": 0.5}),
            ]
        )
        result = Runs.summary_metrics(runs, format="default")
        assert result[0]["run_id"] == "run1"
        assert result[0]["loss"] == 0.5

    def test_skips_empty_summaries(self):
        runs = _make_mock_runs(
            [
                ("run1", {"loss": 0.5}),
                ("run2", {}),
                ("run3", None),
                ("run4", {"loss": 0.1}),
            ]
        )
        result = Runs.summary_metrics(runs, format="default")
        assert len(result) == 2
        assert result[0]["run_id"] == "run1"
        assert result[1]["run_id"] == "run4"

    def test_empty_runs(self):
        runs = _make_mock_runs([])
        result = Runs.summary_metrics(runs, format="default")
        assert result == []

    def test_all_empty_summaries(self):
        runs = _make_mock_runs(
            [
                ("run1", {}),
                ("run2", {}),
            ]
        )
        result = Runs.summary_metrics(runs, format="default")
        assert result == []


class TestSummaryMetricsPolarsFormat:
    def test_returns_polars_dataframe(self):
        runs = _make_mock_runs(
            [
                ("run1", {"loss": 0.5, "accuracy": 0.9}),
                ("run2", {"loss": 0.3, "accuracy": 0.95}),
            ]
        )
        result = Runs.summary_metrics(runs, format="polars")
        assert isinstance(result, pl.DataFrame)
        assert len(result) == 2

    def test_columns_sorted(self):
        runs = _make_mock_runs(
            [
                ("run1", {"z_metric": 1.0, "a_metric": 2.0, "m_metric": 3.0}),
            ]
        )
        result = Runs.summary_metrics(runs, format="polars")
        assert result.columns == ["a_metric", "m_metric", "run_id", "z_metric"]

    def test_includes_run_id_column(self):
        runs = _make_mock_runs(
            [
                ("abc123", {"loss": 0.5}),
            ]
        )
        result = Runs.summary_metrics(runs, format="polars")
        assert "run_id" in result.columns
        assert result["run_id"].to_list() == ["abc123"]

    def test_empty_returns_empty_dataframe(self):
        runs = _make_mock_runs([])
        result = Runs.summary_metrics(runs, format="polars")
        assert isinstance(result, pl.DataFrame)
        assert len(result) == 0

    def test_heterogeneous_metrics(self):
        """Runs with different metric keys produce a DataFrame with all keys."""
        runs = _make_mock_runs(
            [
                ("run1", {"loss": 0.5}),
                ("run2", {"accuracy": 0.9}),
            ]
        )
        result = Runs.summary_metrics(runs, format="polars")
        assert len(result) == 2
        assert set(result.columns) == {"loss", "accuracy", "run_id"}


class TestSummaryMetricsPandasFormat:
    def test_returns_pandas_dataframe(self):
        runs = _make_mock_runs(
            [
                ("run1", {"loss": 0.5, "accuracy": 0.9}),
            ]
        )
        result = Runs.summary_metrics(runs, format="pandas")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    def test_columns_sorted(self):
        runs = _make_mock_runs(
            [
                ("run1", {"z_metric": 1.0, "a_metric": 2.0}),
            ]
        )
        result = Runs.summary_metrics(runs, format="pandas")
        assert list(result.columns) == ["a_metric", "run_id", "z_metric"]

    def test_empty_returns_empty_dataframe(self):
        runs = _make_mock_runs([])
        result = Runs.summary_metrics(runs, format="pandas")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


class TestSummaryMetricsValidation:
    def test_invalid_format_raises_error(self):
        runs = _make_mock_runs([("run1", {"loss": 0.5})])
        with pytest.raises(ValueError, match="Invalid format"):
            Runs.summary_metrics(runs, format="invalid")

    def test_invalid_format_csv(self):
        runs = _make_mock_runs([("run1", {"loss": 0.5})])
        with pytest.raises(ValueError, match="Invalid format"):
            Runs.summary_metrics(runs, format="csv")


class TestSummaryMetricsDoesNotMutate:
    """Verify summary_metrics() does not mutate run.summary_metrics in-place."""

    def test_original_summary_unchanged(self):
        original_summary = {"loss": 0.5, "accuracy": 0.9}
        runs = _make_mock_runs([("run1", original_summary)])
        Runs.summary_metrics(runs, format="default")
        assert "run_id" not in original_summary


class TestSummaryMetricsUpgradeToFull:
    """Verify summary_metrics() calls upgrade_to_full() to load lazy run data."""

    def test_calls_upgrade_to_full(self):
        mock_runs = mock.MagicMock(spec=Runs)
        run1 = _make_mock_run("run1", {"loss": 0.5})
        mock_runs.__iter__ = mock.MagicMock(return_value=iter([run1]))

        Runs.summary_metrics(mock_runs, format="default")

        mock_runs.upgrade_to_full.assert_called_once()


class TestSummaryMetricsErrorHandling:
    """Verify individual run failures don't break the whole collection."""

    def test_failing_run_skipped_with_warning(self):
        mock_runs = mock.MagicMock(spec=Runs)
        run1 = _make_mock_run("run1", {"loss": 0.5})
        run2 = mock.MagicMock()
        run2.id = "run2"
        type(run2).summary_metrics = mock.PropertyMock(
            side_effect=RuntimeError("API error")
        )
        run3 = _make_mock_run("run3", {"loss": 0.1})
        mock_runs.__iter__ = mock.MagicMock(return_value=iter([run1, run2, run3]))

        with mock.patch("wandb.termwarn") as mock_warn:
            result = Runs.summary_metrics(mock_runs, format="default")

        assert len(result) == 2
        assert result[0]["run_id"] == "run1"
        assert result[1]["run_id"] == "run3"
        mock_warn.assert_called_once()
        assert "run2" in mock_warn.call_args[0][0]
