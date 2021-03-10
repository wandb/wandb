#!/usr/bin/env python

import argparse
import csv

from wandb.proto import wandb_telemetry_pb2 as tpb

parser = argparse.ArgumentParser()
parser.add_argument("--output-analytics-csv")
args = parser.parse_args()

csv_fname = args.output_analytics_csv
if csv_fname:
    fieldnames = ['field', 'subfield', 'name']

    with open(csv_fname, "w") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for f in tpb.TelemetryRecord.DESCRIPTOR.fields:
            writer.writerow(dict(field=f.number, name=f.name))
            if f.message_type:
                for sf in f.message_type.fields:
                    writer.writerow(dict(field=f.number, subfield=sf.number, name=sf.name))
