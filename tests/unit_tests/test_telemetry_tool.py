import pytest
from tools import telemetry_tool
from wandb.proto import wandb_telemetry_pb2 as tpb


def test_append_csv_appends_without_rewriting_history(tmp_path):
    path = tmp_path / "telemetry.csv"
    # Key 11 is reserved in TelemetryRecord; owner is an analytics-owned
    # column. The missing trailing newline must not corrupt the appended rows.
    original = (
        "telemetry_record_type,key,dtype,owner\n"
        "imports_init,1,array,data\n"
        "issues,11,array,data"
    )
    path.write_text(original)

    telemetry_tool.append_csv(
        path,
        record="telemetry_record_type",
        descriptor=tpb.TelemetryRecord.DESCRIPTOR,
        dtype=telemetry_tool._telemetry_dtype,
    )

    text = path.read_text()
    assert text.startswith(original + "\n")
    assert "python_version,4,string,\n" in text
    assert "label,9,json,\n" in text
    assert "deprecated,10,array,\n" in text
    assert "_info" not in text


def test_append_csv_rejects_unreserved_removed_key(tmp_path):
    path = tmp_path / "features.csv"
    original = "feature,key\nremoved_without_reserving,1000\n"
    path.write_text(original)

    with pytest.raises(ValueError, match="reserve"):
        telemetry_tool.append_csv(
            path,
            record="feature",
            descriptor=tpb.Feature.DESCRIPTOR,
        )

    assert path.read_text() == original
