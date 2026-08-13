#!/usr/bin/env python
"""Update dbt seed files for telemetry.

Data directory for telemetry records:
    https://github.com/wandb/analytics/tree/master/dbt/data

Usage:
    ./wandb/tools/telemetry_tool.py --output-dir analytics/dbt/seeds/
"""

import argparse
import csv
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from google.protobuf import descriptor_pb2
from google.protobuf.descriptor import Descriptor, FieldDescriptor
from wandb.proto import wandb_telemetry_pb2 as tpb

DEFAULT_DIR = Path("analytics/dbt/seeds")
MetadataFactory = Callable[[FieldDescriptor], Mapping[str, str]]


def _reserved_ranges(descriptor: Descriptor) -> list[tuple[int, int]]:
    file_descriptor = descriptor_pb2.FileDescriptorProto.FromString(
        descriptor.file.serialized_pb
    )
    relative_name = descriptor.full_name.removeprefix(
        f"{file_descriptor.package}."
    ).split(".")
    messages = file_descriptor.message_type

    for name in relative_name:
        message = next(message for message in messages if message.name == name)
        messages = message.nested_type

    return [(reserved.start, reserved.end) for reserved in message.reserved_range]


def _is_reserved(number: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return any(start <= number < end for start, end in ranges)


def _telemetry_record_metadata(field: FieldDescriptor) -> Mapping[str, str]:
    if field.is_repeated:
        return {"dtype": "array"}

    if field.message_type is None:
        return {"dtype": "string"}

    nested_fields = field.message_type.fields
    if nested_fields and all(
        nested.type == FieldDescriptor.TYPE_BOOL for nested in nested_fields
    ):
        return {"dtype": "array"}

    return {"dtype": "json"}


def append_csv(
    path: Path,
    *,
    record: str,
    descriptor: Descriptor,
    metadata_factory: MetadataFactory | None = None,
) -> None:
    """Append new protobuf fields without changing existing analytics mappings."""
    metadata_fields = (
        list(metadata_factory(descriptor.fields[0])) if metadata_factory else []
    )
    expected_fieldnames = [record, "key", *metadata_fields]
    existing_rows: list[dict[str, str]] = []

    if path.exists():
        with path.open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if reader.fieldnames is None:
                raise ValueError(f"{path} has no header")
            missing_columns = set(expected_fieldnames) - set(reader.fieldnames)
            if missing_columns:
                missing = ", ".join(sorted(missing_columns))
                raise ValueError(f"{path} is missing required column(s): {missing}")
            fieldnames = reader.fieldnames
            existing_rows = list(reader)
    else:
        fieldnames = expected_fieldnames

    fields_by_number = {field.number: field for field in descriptor.fields}
    public_fields = [
        field for field in descriptor.fields if not field.name.startswith("_")
    ]
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
    for field in public_fields:
        if field.number in existing_numbers:
            continue
        if field.name in existing_names:
            raise ValueError(
                f"{path} already maps {record} {field.name!r} to a different key"
            )

        row: dict[str, str | int] = {record: field.name, "key": field.number}
        if metadata_factory:
            row.update(metadata_factory(field))
        new_rows.append(row)

    if not new_rows and path.exists():
        return

    print("Writing:", path)
    mode = "a" if path.exists() else "w"
    needs_newline = False
    if mode == "a" and path.stat().st_size:
        with path.open("rb") as csv_file:
            csv_file.seek(-1, 2)
            needs_newline = csv_file.read(1) != b"\n"

    with path.open(mode, newline="") as csv_file:
        if needs_newline:
            csv_file.write("\n")
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, lineterminator="\n")
        if mode == "w":
            writer.writeheader()
        writer.writerows(new_rows)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", default=DEFAULT_DIR if DEFAULT_DIR.exists() else Path()
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
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    outputs = [
        (
            "telemetry_record_type",
            tpb.TelemetryRecord.DESCRIPTOR,
            args.output_telemetry_record_types,
            _telemetry_record_metadata,
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

    for record, descriptor, filename, metadata_factory in outputs:
        append_csv(
            output_dir / filename,
            record=record,
            descriptor=descriptor,
            metadata_factory=metadata_factory,
        )


if __name__ == "__main__":
    main()
