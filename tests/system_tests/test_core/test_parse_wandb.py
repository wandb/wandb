from __future__ import annotations

import io
import json
import pathlib

import pytest
import wandb
from wandb.cli import parse_wandb


@pytest.fixture()
def run_file(tmp_path: pathlib.Path) -> str:
    with wandb.init(dir=tmp_path, mode="offline") as run:
        run.log({"loss": 0.5, "acc": 0.8})
        run.log({"loss": 0.3, "acc": 0.9})
        sync_file = run.settings.sync_file
    return sync_file


def test_parse_returns_expected_records(run_file):
    buf = io.StringIO()
    parse_wandb.parse(
        pathlib.Path(run_file),
        output=buf,
        record_types=None,
    )
    records = [json.loads(line) for line in buf.getvalue().strip().splitlines()]

    for r in records:
        assert isinstance(r, dict)
    record_types = [r["record_type"] for r in records]
    assert "run" in record_types
    assert "exit" in record_types
    assert record_types.count("history") >= 2

    history_records = [r for r in records if r["record_type"] == "history"]

    expected = [
        {"loss": 0.5, "acc": 0.8},
        {"loss": 0.3, "acc": 0.9},
    ]
    for record, exp in zip(history_records, expected):
        content = json.loads(record["json_content"])
        step = {
            item["nested_key"][0]: item["value_json"]
            for item in content["history"]["item"]
        }
        for key, val in exp.items():
            assert float(step[key]) == pytest.approx(val)


def test_filter_single_type(run_file):
    buf = io.StringIO()
    parse_wandb.parse(
        pathlib.Path(run_file),
        output=buf,
        record_types=["history"],
    )
    records = [json.loads(line) for line in buf.getvalue().strip().splitlines()]

    assert all(r["record_type"] == "history" for r in records)


def test_filter_multiple_types(run_file):
    buf = io.StringIO()
    parse_wandb.parse(
        pathlib.Path(run_file),
        output=buf,
        record_types=["run", "exit"],
    )
    records = [json.loads(line) for line in buf.getvalue().strip().splitlines()]

    assert all(r["record_type"] in ("run", "exit") for r in records)


def test_parse__page_size_returns_all_records(run_file):
    buf_all = io.StringIO()
    parse_wandb.parse(
        pathlib.Path(run_file),
        output=buf_all,
        record_types=None,
    )
    all_records = [json.loads(line) for line in buf_all.getvalue().strip().splitlines()]

    buf_paged = io.StringIO()
    parse_wandb.parse(
        pathlib.Path(run_file),
        output=buf_paged,
        record_types=None,
        page_size=1,
    )
    paginated = [json.loads(line) for line in buf_paged.getvalue().strip().splitlines()]

    assert paginated == all_records


def test_output_file_created(run_file, tmp_path):
    out = tmp_path / "out.jsonl"
    with open(out, "w") as f:
        parse_wandb.parse(
            pathlib.Path(run_file),
            output=f,
            record_types=None,
        )
    assert out.exists()
    lines = out.read_text().strip().splitlines()
    assert len(lines) > 0
    for line in lines:
        record = json.loads(line)
        assert "record_type" in record
        assert "json_content" in record


def test_missing_file_raises(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        parse_wandb.parse(
            tmp_path / "nonexistent.wandb",
            output=io.StringIO(),
            record_types=None,
        )
