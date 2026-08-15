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
from collections.abc import Callable, Sequence
from pathlib import Path

from google.protobuf import descriptor_pb2
from google.protobuf.descriptor import Descriptor, FieldDescriptor
from wandb.proto import wandb_telemetry_pb2 as tpb

DEFAULT_DIR = Path("analytics/dbt/seeds")


def _reserved_ranges(descriptor: Descriptor) -> list[tuple[int, int]]:
    proto = descriptor_pb2.DescriptorProto()
    descriptor.CopyToProto(proto)
    return [(r.start, r.end) for r in proto.reserved_range]


def _is_reserved(number: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return any(start <= number < end for start, end in ranges)


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
    required_columns = [record, "key"] + (["dtype"] if dtype else [])
    fieldnames = required_columns
    existing_rows: list[dict[str, str]] = []
    text = ""

    if path.exists():
        text = path.read_text()
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValueError(f"{path} has no header")
        missing_columns = set(required_columns) - set(reader.fieldnames)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"{path} is missing required column(s): {missing}")
        fieldnames = list(reader.fieldnames)
        existing_rows = list(reader)

    fields_by_number = {field.number: field for field in descriptor.fields}
    reserved_ranges = _reserved_ranges(descriptor)
    existing_numbers: set[int] = set()
    existing_names: set[str] = set()

    for line_number, row in enumerate(existing_rows, start=2):
        try:
            number = int(row["key"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{path}:{line_number} has an invalid key") from error

        name = row[record]
        if number in existing_numbers:
            raise ValueError(f"{path}:{line_number} repeats key {number}")
        if name in existing_names:
            raise ValueError(f"{path}:{line_number} repeats {record} {name!r}")

        existing_numbers.add(number)
        existing_names.add(name)
        field = fields_by_number.get(number)
        if field is not None and field.name != name:
            raise ValueError(
                f"{path}:{line_number} maps key {number} to {name!r}, "
                f"but the proto maps it to {field.name!r}"
            )
        if field is None and not _is_reserved(number, reserved_ranges):
            raise ValueError(
                f"{path}:{line_number} maps removed key {number}; "
                f"reserve it in {descriptor.full_name} before removing the field"
            )

    new_rows: list[dict[str, str | int]] = []
    for field in descriptor.fields:
        # skip private fields and fields the file already maps
        if field.name.startswith("_") or field.number in existing_numbers:
            continue
        if field.name in existing_names:
            raise ValueError(
                f"{path} already maps {record} {field.name!r} to a different key"
            )

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
    parser.add_argument(
        "--output-telemetry-record-types",
        default="map_run_cli_telemetry_record_types.csv",
    )
    parser.add_argument("--output-imports", default="map_run_cli_imports.csv")
    parser.add_argument("--output-features", default="map_run_cli_features.csv")
    parser.add_argument("--output-environments", default="map_run_cli_environments.csv")
    parser.add_argument("--output-labels", default="map_run_cli_labels.csv")
    parser.add_argument(
        "--output-deprecated-features", default="map_run_cli_deprecated.csv"
    )
    args = parser.parse_args()

    outputs = [
        (
            "telemetry_record_type",
            tpb.TelemetryRecord.DESCRIPTOR,
            args.output_telemetry_record_types,
            _telemetry_dtype,
        ),
        ("import", tpb.Imports.DESCRIPTOR, args.output_imports, None),
        ("feature", tpb.Feature.DESCRIPTOR, args.output_features, None),
        ("environment", tpb.Env.DESCRIPTOR, args.output_environments, None),
        ("label", tpb.Labels.DESCRIPTOR, args.output_labels, None),
        (
            "deprecated_feature",
            tpb.Deprecated.DESCRIPTOR,
            args.output_deprecated_features,
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
