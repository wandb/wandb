"""System tests for ``wandb parse`` — full Python → wandb-core round-trip.

These tests exercise the complete pipeline with no mocks:
  Python CLI / parse_wandb → ServiceApi → wandb-core (Go) →
  transactionlog.Reader → ParseRunFileResponse → JSON output

wandb-core is started as a real subprocess by ServiceApi.ensure_service().
No W&B backend server is needed; everything runs locally.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import wandb

from wandb.cli import parse_wandb


@pytest.fixture()
def run_file(tmp_path: pathlib.Path) -> str:
    """Create a .wandb file with known content via an offline run."""
    with wandb.init(dir=tmp_path, mode="offline") as run:
        run.log({"loss": 0.5, "acc": 0.8})
        run.log({"loss": 0.3, "acc": 0.9})
        sync_file = run.settings.sync_file
    return sync_file


def _parse_to_records(
    run_file: str,
    tmp_path: pathlib.Path,
    *,
    record_types: list[str] | None = None,
    page_size: int = 100,
) -> list[dict]:
    """Helper: run parse_wandb.parse and return parsed JSON records."""
    out = tmp_path / "output.jsonl"
    parse_wandb.parse(
        run_file,
        output=str(out),
        record_types=record_types,
        page_size=page_size,
    )
    return [json.loads(line) for line in out.read_text().strip().splitlines() if line]


class TestParseAllRecords:
    """Verify that parsing returns the expected record types."""

    def test_returns_multiple_records(self, run_file, tmp_path):
        records = _parse_to_records(run_file, tmp_path)
        assert len(records) > 0

    def test_contains_run_record(self, run_file, tmp_path):
        records = _parse_to_records(run_file, tmp_path)
        assert any("run" in r for r in records)

    def test_contains_history_records(self, run_file, tmp_path):
        records = _parse_to_records(run_file, tmp_path)
        history = [r for r in records if "history" in r]
        assert len(history) >= 2

    def test_contains_exit_record(self, run_file, tmp_path):
        records = _parse_to_records(run_file, tmp_path)
        assert any("exit" in r for r in records)

    def test_every_record_is_valid_json_object(self, run_file, tmp_path):
        records = _parse_to_records(run_file, tmp_path)
        for r in records:
            assert isinstance(r, dict)


class TestParseHistoryValues:
    """Verify that history records contain the exact values we logged."""

    def test_first_step_values(self, run_file, tmp_path):
        records = _parse_to_records(run_file, tmp_path, record_types=["history"])
        items = {
            item["key"]: item["value_json"]
            for item in records[0]["history"]["item"]
        }
        assert float(items["loss"]) == pytest.approx(0.5)
        assert float(items["acc"]) == pytest.approx(0.8)

    def test_second_step_values(self, run_file, tmp_path):
        records = _parse_to_records(run_file, tmp_path, record_types=["history"])
        items = {
            item["key"]: item["value_json"]
            for item in records[1]["history"]["item"]
        }
        assert float(items["loss"]) == pytest.approx(0.3)
        assert float(items["acc"]) == pytest.approx(0.9)


class TestRecordTypeFilter:
    """Verify the --record-types filter works end-to-end."""

    def test_filter_history_only(self, run_file, tmp_path):
        records = _parse_to_records(run_file, tmp_path, record_types=["history"])
        for r in records:
            assert "history" in r
            assert "run" not in r
            assert "exit" not in r

    def test_filter_exit_only(self, run_file, tmp_path):
        records = _parse_to_records(run_file, tmp_path, record_types=["exit"])
        assert len(records) == 1
        assert "exit" in records[0]

    def test_filter_multiple_types(self, run_file, tmp_path):
        records = _parse_to_records(
            run_file, tmp_path, record_types=["run", "exit"]
        )
        for r in records:
            assert "run" in r or "exit" in r


class TestPagination:
    """Verify that small page sizes still yield the full result set."""

    def test_page_size_one(self, run_file, tmp_path):
        all_records = _parse_to_records(run_file, tmp_path, page_size=100)
        paginated = _parse_to_records(run_file, tmp_path / "paged", page_size=1)
        assert len(paginated) == len(all_records)

    def test_page_size_two(self, run_file, tmp_path):
        all_records = _parse_to_records(run_file, tmp_path, page_size=100)
        paginated = _parse_to_records(run_file, tmp_path / "paged", page_size=2)
        assert len(paginated) == len(all_records)


class TestOutputFile:
    """Verify writing to an output file works."""

    def test_output_file_created(self, run_file, tmp_path):
        out = tmp_path / "out.jsonl"
        parse_wandb.parse(
            run_file, output=str(out), record_types=None, page_size=100
        )
        assert out.exists()
        assert out.stat().st_size > 0

    def test_output_file_contains_valid_json(self, run_file, tmp_path):
        out = tmp_path / "out.jsonl"
        parse_wandb.parse(
            run_file, output=str(out), record_types=None, page_size=100
        )
        for line in out.read_text().strip().splitlines():
            json.loads(line)


class TestErrorHandling:
    """Verify error cases."""

    def test_missing_file_raises(self, tmp_path):
        from wandb.sdk.lib.service.service_connection import WandbApiFailedError

        with pytest.raises(WandbApiFailedError):
            parse_wandb.parse(
                str(tmp_path / "nonexistent.wandb"),
                output=str(tmp_path / "out.jsonl"),
                record_types=None,
                page_size=100,
            )
