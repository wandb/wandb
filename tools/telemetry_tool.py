#!/usr/bin/env python
"""Update dbt seed files for telemetry.

Data directory for telemetry records:
    https://github.com/wandb/analytics/tree/master/dbt/data

Usage:
    ./wandb/tools/telemetry_tool.py --output-dir analytics/dbt/seeds/
"""

import argparse
import csv
import io
from collections.abc import Callable
from pathlib import Path

from google.protobuf import descriptor_pb2
from google.protobuf.descriptor import Descriptor, FieldDescriptor
from wandb.proto import wandb_telemetry_pb2 as tpb

DEFAULT_DIR = Path("analytics/dbt/seeds")


def _telemetry_dtype(field: FieldDescriptor) -> str:
    """Return the dtype the analytics model expects for a root telemetry field."""
    if field.is_repeated:
        return "array"

    if field.message_type is None:
        return "string"

    # Messages of bool flags (Imports, Feature, Env, Deprecated) are stored
    # as arrays of the flags that are set; other messages are stored as JSON.
    nested_fields = field.message_type.fields
    if nested_fields and all(
        nested.type == FieldDescriptor.TYPE_BOOL for nested in nested_fields
    ):
        return "array"

    return "json"


def append_csv(
    path: Path,
    *,
    record: str,
    descriptor: Descriptor,
    dtype: Callable[[FieldDescriptor], str] | None = None,
) -> None:
    """Append new protobuf fields without changing existing analytics mappings."""
    text = path.read_text() if path.exists() else ""
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or [record, "key", *(["dtype"] if dtype else [])]
    existing_keys = {int(row["key"]) for row in reader}

    proto = descriptor_pb2.DescriptorProto()
    descriptor.CopyToProto(proto)
    active_keys = {field.number for field in descriptor.fields}
    removed_keys = [
        key
        for key in sorted(existing_keys - active_keys)
        if not any(r.start <= key < r.end for r in proto.reserved_range)
    ]
    if removed_keys:
        raise ValueError(
            f"{path} maps removed keys {removed_keys}; "
            f"reserve them in {descriptor.full_name} before removing fields"
        )

    new_rows: list[dict[str, str | int]] = []
    for field in descriptor.fields:
        # skip private fields and fields the file already maps
        if field.name.startswith("_") or field.number in existing_keys:
            continue
        row: dict[str, str | int] = {record: field.name, "key": field.number}
        if dtype:
            row["dtype"] = dtype(field)
        new_rows.append(row)

    if not new_rows and text:
        return

    print("Writing:", path)
    with path.open("a", newline="") as csv_file:
        if text and not text.endswith("\n"):
            csv_file.write("\n")
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, lineterminator="\n")
        if not text:
            writer.writeheader()
        writer.writerows(new_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_DIR if DEFAULT_DIR.exists() else Path(),
    )
    args = parser.parse_args()

    outputs = [
        (
            "telemetry_record_type",
            tpb.TelemetryRecord.DESCRIPTOR,
            "map_run_cli_telemetry_record_types.csv",
            _telemetry_dtype,
        ),
        ("import", tpb.Imports.DESCRIPTOR, "map_run_cli_imports.csv", None),
        ("feature", tpb.Feature.DESCRIPTOR, "map_run_cli_features.csv", None),
        ("environment", tpb.Env.DESCRIPTOR, "map_run_cli_environments.csv", None),
        ("label", tpb.Labels.DESCRIPTOR, "map_run_cli_labels.csv", None),
        (
            "deprecated_feature",
            tpb.Deprecated.DESCRIPTOR,
            "map_run_cli_deprecated.csv",
            None,
        ),
    ]

    for record, descriptor, filename, dtype in outputs:
        append_csv(
            args.output_dir / filename,
            record=record,
            descriptor=descriptor,
            dtype=dtype,
        )


if __name__ == "__main__":
    main()
