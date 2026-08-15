import csv

import pytest
from tools import telemetry_tool
from wandb.proto import wandb_telemetry_pb2 as tpb


def test_append_csv_preserves_reserved_rows_and_metadata(tmp_path):
    path = tmp_path / "telemetry.csv"
    original = (
        "telemetry_record_type,key,dtype,owner\n"
        "imports_init,1,array,data\n"
        "issues,11,array,data\n"
    )
    path.write_text(original)

    telemetry_tool.append_csv(
        path,
        record="telemetry_record_type",
        descriptor=tpb.TelemetryRecord.DESCRIPTOR,
        dtype=telemetry_tool._telemetry_dtype,
    )

    assert path.read_text().startswith(original)
    with path.open(newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    rows_by_key = {int(row["key"]): row for row in rows}
    assert rows_by_key[11] == {
        "telemetry_record_type": "issues",
        "key": "11",
        "dtype": "array",
        "owner": "data",
    }
    assert rows_by_key[4]["dtype"] == "string"
    assert rows_by_key[9]["dtype"] == "json"
    assert rows_by_key[10]["dtype"] == "array"
    assert rows_by_key[4]["owner"] == ""


def test_append_csv_handles_missing_final_newline(tmp_path):
    path = tmp_path / "features.csv"
    original = "feature,key\nimporter_mlflow,48"
    path.write_text(original)

    telemetry_tool.append_csv(
        path,
        record="feature",
        descriptor=tpb.Feature.DESCRIPTOR,
    )

    assert path.read_text().startswith(f"{original}\nwatch,1\n")


def test_append_csv_rejects_unreserved_removed_key(tmp_path):
    path = tmp_path / "features.csv"
    path.write_text("feature,key\nremoved_without_reserving,1000\n")

    with pytest.raises(ValueError, match="reserve it in wandb_internal.Feature"):
        telemetry_tool.append_csv(
            path,
            record="feature",
            descriptor=tpb.Feature.DESCRIPTOR,
        )

    assert path.read_text() == "feature,key\nremoved_without_reserving,1000\n"


def test_append_csv_requires_analytics_metadata(tmp_path):
    path = tmp_path / "telemetry.csv"
    contents = "telemetry_record_type,key\nimports_init,1\n"
    path.write_text(contents)

    with pytest.raises(ValueError, match="missing required column.*dtype"):
        telemetry_tool.append_csv(
            path,
            record="telemetry_record_type",
            descriptor=tpb.TelemetryRecord.DESCRIPTOR,
            dtype=telemetry_tool._telemetry_dtype,
        )

    assert path.read_text() == contents


def test_append_csv_creates_telemetry_map_with_dtypes(tmp_path):
    path = tmp_path / "telemetry.csv"

    telemetry_tool.append_csv(
        path,
        record="telemetry_record_type",
        descriptor=tpb.TelemetryRecord.DESCRIPTOR,
        dtype=telemetry_tool._telemetry_dtype,
    )

    with path.open(newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = list(reader)

    assert reader.fieldnames == ["telemetry_record_type", "key", "dtype"]
    assert {row["telemetry_record_type"]: row["dtype"] for row in rows} == {
        "imports_init": "array",
        "imports_finish": "array",
        "feature": "array",
        "python_version": "string",
        "cli_version": "string",
        "huggingface_version": "string",
        "env": "array",
        "label": "json",
        "deprecated": "array",
        "core_version": "string",
        "platform": "string",
    }
