#!/usr/bin/env python
"""Generate dbt files for telemetry.

Data directory for telemetry records:
    https://github.com/wandb/analytics/tree/master/dbt/data

Usage:
    ./client/tools/telemetry-tool.py --output-dir analytics/dbt/data/
"""

import argparse
import csv
import os
from typing import Any, List

from wandb.proto import wandb_telemetry_pb2 as tpb


DEFAULT_DIR: str = "analytics/dbt/data"
parser = argparse.ArgumentParser()
parser.add_argument(
    "--output-dir", default=DEFAULT_DIR if os.path.exists(DEFAULT_DIR) else ""
)
parser.add_argument(
    "--output-telemetry-record-types", default="map_run_cli_telemetry_record_types.csv"
)
parser.add_argument("--output-imports", default="map_run_cli_imports.csv")
parser.add_argument("--output-features", default="map_run_cli_features.csv")
parser.add_argument("--output-environments", default="map_run_cli_environments.csv")
parser.add_argument("--output-labels", default="map_run_cli_labels.csv")
args = parser.parse_args()


def write_csv(record: str, fields: List[Any]):
    record_arg = "output_{}s".format(record)
    fname = os.path.join(args.output_dir, getattr(args, record_arg))
    print("Writing:", fname)
    with open(fname, "w") as fp:
        writer = csv.DictWriter(fp, fieldnames=[record, "key"], lineterminator="\n")
        writer.writeheader()
        for f in fields:
            writer.writerow({record: f.name, "key": f.number})


def main():
    telemetry_records = list(tpb.TelemetryRecord.DESCRIPTOR.fields)
    write_csv(record="telemetry_record_type", fields=telemetry_records)

    import_records = list(tpb.Imports.DESCRIPTOR.fields)
    write_csv(record="import", fields=import_records)

    feature_records = list(tpb.Feature.DESCRIPTOR.fields)
    write_csv(record="feature", fields=feature_records)

    env_records = list(tpb.Env.DESCRIPTOR.fields)
    write_csv(record="environment", fields=env_records)

    label_records = list(tpb.Labels.DESCRIPTOR.fields)
    write_csv(record="label", fields=label_records)


if __name__ == "__main__":
    main()
