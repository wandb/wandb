"""Parse `go test -bench` output for this package into a CSV table.

Benchmark names have the shape:

    Benchmark<Op>/<dataset>/<value_mode>/<payload_format>/<envelope_format>

e.g. `BenchmarkEncode/dense_numeric/typed_value/row_proto/native`, optionally
with a trailing `-<GOMAXPROCS>` (e.g. `native-18`) that `go test` appends when
it isn't pinned to 1. Older logs used a combined format component
(`Benchmark<Op>/<dataset>/<value_mode>/<format>`, e.g. `proto_row_proto`) with
different value-mode names; those are parsed too and normalized into the new
payload_format / envelope_format / value_mode vocabulary.

Each result line carries `iterations` followed by alternating `<value> <unit>`
pairs (`1987 ns/op`, `117.25 MB/s`, `156.0 body_bytes`, ...); Encode lines
report more custom metrics (body/envelope/gzip sizes and ratios) than Decode
lines. Both report `ops/s` directly when the benchmark reports it; otherwise
it's derived from `ns/op`.

Usage:
    python3 parse_bench.py bench-run.log            # writes bench-run.csv
    python3 parse_bench.py bench-run.log -o out.csv
    python3 parse_bench.py bench-run.log -o -       # CSV to stdout
"""
import argparse
import csv
import os
import re
import sys

PAYLOAD_FORMATS = {"jsonl", "row_proto", "column_proto"}
ENVELOPE_FORMATS = {"json", "native"}
VALUE_MODES = {"json_value", "typed_value"}

# Older logs combined payload+envelope in one component and used different
# value-mode names; map them into the new vocabulary.
OLD_FORMAT_MAP = {
    "legacy_json_jsonl": ("jsonl", "json"),
    "json_row_proto_b64": ("row_proto", "json"),
    "proto_row_proto": ("row_proto", "native"),
    "json_column_proto_b64": ("column_proto", "json"),
    "proto_column_proto": ("column_proto", "native"),
}
OLD_VALUE_MODE_MAP = {"value_json_only": "json_value", "typed_only": "typed_value"}

NEW_NAME_RE = re.compile(
    r"^Benchmark(?P<op>\w+)/(?P<dataset>[^/]+)/(?P<value_mode>[^/]+)"
    r"/(?P<payload>[^/]+)/(?P<envelope>[^/]+?)(?:-\d+)?$"
)
OLD_NAME_RE = re.compile(
    r"^Benchmark(?P<op>\w+)/(?P<dataset>[^/]+)/(?P<value_mode>[^/]+)"
    r"/(?P<format>[^/]+?)(?:-\d+)?$"
)
METRIC_RE = re.compile(r"([-\d.]+)\s+([A-Za-z][^\s]*)")

KNOWN_COLUMNS = [
    "benchmark", "op", "dataset", "value_mode",
    "payload_format", "envelope_format", "iterations",
]


def unit_to_column(unit):
    return unit.replace("/", "_per_").replace("%", "pct").lower()


def parse_name(name):
    """Return (op, dataset, value_mode, payload_format, envelope_format) or None.

    Values are validated against the known vocabularies so that unrelated
    benchmarks with slash-separated names (e.g. BenchmarkCompress's trailing
    /gzipN component) are skipped rather than mis-parsed.
    """
    m = NEW_NAME_RE.match(name)
    if m and (
        m.group("value_mode") in VALUE_MODES
        and m.group("payload") in PAYLOAD_FORMATS
        and m.group("envelope") in ENVELOPE_FORMATS
    ):
        return (m.group("op"), m.group("dataset"), m.group("value_mode"),
                m.group("payload"), m.group("envelope"))

    m = OLD_NAME_RE.match(name)
    if m and m.group("value_mode") in OLD_VALUE_MODE_MAP and m.group("format") in OLD_FORMAT_MAP:
        payload, envelope = OLD_FORMAT_MAP[m.group("format")]
        return (m.group("op"), m.group("dataset"),
                OLD_VALUE_MODE_MAP[m.group("value_mode")], payload, envelope)

    return None


def parse_line(line):
    if not line.startswith("Benchmark"):
        return None
    parts = line.split(None, 2)
    if len(parts) < 3:
        return None
    name, iterations, rest = parts
    parsed = parse_name(name)
    if not parsed:
        return None
    op, dataset, value_mode, payload, envelope = parsed
    row = {
        "benchmark": name,
        "op": op,
        "dataset": dataset,
        "value_mode": value_mode,
        "payload_format": payload,
        "envelope_format": envelope,
        "iterations": int(iterations),
    }
    for value, unit in METRIC_RE.findall(rest):
        row[unit_to_column(unit)] = float(value)
    if row.get("ops_per_s") is not None:
        # Prefer the benchmark's own ops/s measurement over a derived one.
        row["ops_per_sec"] = row.pop("ops_per_s")
    elif row.get("ns_per_op"):
        row["ops_per_sec"] = 1e9 / row["ns_per_op"]
    return row


def parse_log(path):
    rows = []
    meta = {}
    with open(path) as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if line.startswith("Benchmark"):
                row = parse_line(line)
                if row:
                    rows.append(row)
            elif line.startswith(("goos:", "goarch:", "pkg:", "cpu:")):
                key, _, val = line.partition(":")
                meta[key.strip()] = val.strip()
    return meta, rows


def write_csv(rows, out):
    extra_cols = sorted({k for row in rows for k in row} - set(KNOWN_COLUMNS))
    fieldnames = KNOWN_COLUMNS + extra_cols
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logfile")
    ap.add_argument("-o", "--csv", default=None,
                    help="output CSV path (default: <logfile minus extension>.csv; use '-' for stdout)")
    args = ap.parse_args()

    meta, rows = parse_log(args.logfile)
    if not rows:
        sys.exit(f"no benchmark lines found in {args.logfile}")

    out_path = args.csv or os.path.splitext(args.logfile)[0] + ".csv"
    if out_path == "-":
        write_csv(rows, sys.stdout)
    else:
        with open(out_path, "w", newline="") as out:
            write_csv(rows, out)
        print(f"wrote {len(rows)} rows to {out_path}", file=sys.stderr)

    for k, v in meta.items():
        print(f"# {k}: {v}", file=sys.stderr)


if __name__ == "__main__":
    main()
