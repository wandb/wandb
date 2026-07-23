"""Parse `go test -bench` output for this package into a CSV table.

Benchmark names have the shape:

    Benchmark<Op>/<dataset>/<value_mode>/<format>

e.g. `BenchmarkEncode/dense_numeric/typed_only/proto_row_proto`, optionally
with a trailing `-<GOMAXPROCS>` (e.g. `proto_row_proto-18`) that `go test`
appends when it isn't pinned to 1. Each result line carries `iterations`
followed by alternating `<value> <unit>` pairs (`1987 ns/op`, `117.25 MB/s`,
`156.0 body_bytes`, ...); Encode lines report more custom metrics
(body/envelope/gzip sizes and ratios) than Decode lines. Both report `ops/s`
directly when the benchmark reports it; otherwise it's derived from `ns/op`.

Usage:
    python3 parse_bench.py bench-run.log -o bench.csv
    python3 parse_bench.py bench-run.log        # CSV to stdout
"""
import argparse
import csv
import re
import sys

NAME_RE = re.compile(
    r"^Benchmark(?P<op>\w+)/(?P<dataset>[^/]+)/(?P<value_mode>[^/]+)/(?P<format>[^/]+?)(?:-\d+)?$"
)
METRIC_RE = re.compile(r"([-\d.]+)\s+([A-Za-z][^\s]*)")

KNOWN_COLUMNS = ["benchmark", "op", "dataset", "value_mode", "format", "iterations"]


def unit_to_column(unit):
    return unit.replace("/", "_per_").replace("%", "pct").lower()


def parse_line(line):
    if not line.startswith("Benchmark"):
        return None
    parts = line.split(None, 2)
    if len(parts) < 3:
        return None
    name, iterations, rest = parts
    m = NAME_RE.match(name)
    if not m:
        return None
    row = {
        "benchmark": name,
        "op": m.group("op"),
        "dataset": m.group("dataset"),
        "value_mode": m.group("value_mode"),
        "format": m.group("format"),
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
    ap.add_argument("-o", "--csv", default=None, help="write CSV here (default: stdout)")
    args = ap.parse_args()

    meta, rows = parse_log(args.logfile)
    if not rows:
        sys.exit(f"no benchmark lines found in {args.logfile}")

    if args.csv:
        with open(args.csv, "w", newline="") as out:
            write_csv(rows, out)
        print(f"wrote {len(rows)} rows to {args.csv}", file=sys.stderr)
    else:
        write_csv(rows, sys.stdout)

    for k, v in meta.items():
        print(f"# {k}: {v}", file=sys.stderr)


if __name__ == "__main__":
    main()
