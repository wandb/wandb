"""Tests for Runs.configs() method."""

from __future__ import annotations

from unittest import mock

import pandas as pd
import polars as pl
import pytest
from wandb.apis.public.runs import Runs


def _make_mock_run(run_id: str, config: dict | None = None):
    """Create a mock Run with the given id and config."""
    run = mock.MagicMock()
    run.id = run_id
    run.config = config if config is not None else {}
    return run


def _make_mock_runs(run_specs: list[tuple[str, dict | None]]):
    """Create a mock Runs object that iterates over mock runs.

    Args:
        run_specs: List of (run_id, config) tuples.
    """
    mock_runs = mock.MagicMock(spec=Runs)
    mock_run_objects = [_make_mock_run(rid, cfg) for rid, cfg in run_specs]
    mock_runs.__iter__ = mock.MagicMock(return_value=iter(mock_run_objects))
    return mock_runs


class TestConfigsDefaultFormat:
    def test_returns_list_of_dicts(self):
        runs = _make_mock_runs(
            [
                ("run1", {"lr": 0.01, "epochs": 10}),
                ("run2", {"lr": 0.001, "epochs": 20}),
            ]
        )
        result = Runs.configs(runs, format="default")
        assert isinstance(result, list)
        assert len(result) == 2

    def test_includes_run_id(self):
        runs = _make_mock_runs(
            [
                ("run1", {"lr": 0.01}),
            ]
        )
        result = Runs.configs(runs, format="default")
        assert result[0]["run_id"] == "run1"
        assert result[0]["lr"] == 0.01

    def test_skips_empty_configs(self):
        runs = _make_mock_runs(
            [
                ("run1", {"lr": 0.01}),
                ("run2", {}),
                ("run3", None),
                ("run4", {"lr": 0.1}),
            ]
        )
        result = Runs.configs(runs, format="default")
        assert len(result) == 2
        assert result[0]["run_id"] == "run1"
        assert result[1]["run_id"] == "run4"

    def test_empty_runs(self):
        runs = _make_mock_runs([])
        result = Runs.configs(runs, format="default")
        assert result == []

    def test_all_empty_configs(self):
        runs = _make_mock_runs(
            [
                ("run1", {}),
                ("run2", {}),
            ]
        )
        result = Runs.configs(runs, format="default")
        assert result == []


class TestConfigsPolarsFormat:
    def test_returns_polars_dataframe(self):
        runs = _make_mock_runs(
            [
                ("run1", {"lr": 0.01, "epochs": 10}),
                ("run2", {"lr": 0.001, "epochs": 20}),
            ]
        )
        result = Runs.configs(runs, format="polars")
        assert isinstance(result, pl.DataFrame)
        assert len(result) == 2

    def test_columns_sorted(self):
        runs = _make_mock_runs(
            [
                ("run1", {"z_param": 1, "a_param": 2, "m_param": 3}),
            ]
        )
        result = Runs.configs(runs, format="polars")
        assert result.columns == ["a_param", "m_param", "run_id", "z_param"]

    def test_includes_run_id_column(self):
        runs = _make_mock_runs(
            [
                ("abc123", {"lr": 0.01}),
            ]
        )
        result = Runs.configs(runs, format="polars")
        assert "run_id" in result.columns
        assert result["run_id"].to_list() == ["abc123"]

    def test_empty_returns_empty_dataframe(self):
        runs = _make_mock_runs([])
        result = Runs.configs(runs, format="polars")
        assert isinstance(result, pl.DataFrame)
        assert len(result) == 0

    def test_heterogeneous_configs(self):
        """Runs with different config keys produce a DataFrame with all keys."""
        runs = _make_mock_runs(
            [
                ("run1", {"lr": 0.01}),
                ("run2", {"batch_size": 32}),
            ]
        )
        result = Runs.configs(runs, format="polars")
        assert len(result) == 2
        assert set(result.columns) == {"lr", "batch_size", "run_id"}


class TestConfigsPandasFormat:
    def test_returns_pandas_dataframe(self):
        runs = _make_mock_runs(
            [
                ("run1", {"lr": 0.01, "epochs": 10}),
            ]
        )
        result = Runs.configs(runs, format="pandas")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    def test_columns_sorted(self):
        runs = _make_mock_runs(
            [
                ("run1", {"z_param": 1, "a_param": 2}),
            ]
        )
        result = Runs.configs(runs, format="pandas")
        assert list(result.columns) == ["a_param", "run_id", "z_param"]

    def test_empty_returns_empty_dataframe(self):
        runs = _make_mock_runs([])
        result = Runs.configs(runs, format="pandas")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


class TestConfigsValidation:
    def test_invalid_format_raises_error(self):
        runs = _make_mock_runs([("run1", {"lr": 0.01})])
        with pytest.raises(Exception, match="Invalid format"):
            Runs.configs(runs, format="invalid")

    def test_invalid_format_csv(self):
        runs = _make_mock_runs([("run1", {"lr": 0.01})])
        with pytest.raises(Exception, match="Invalid format"):
            Runs.configs(runs, format="csv")
