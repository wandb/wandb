#!/usr/bin/env bash
# Run the filestream encoding SDK benchmark, then parse results and build a dashboard.
#
# Usage:
#   ./run_sdk_bench.sh [-n PROCESSORS] [-t SECONDS]
#
# Output (in ~/code/benchmarks):
#   sdk-bench-YYYYMMDD-HHMM.log
#   sdk-bench-YYYYMMDD-HHMM.csv
#   sdk-bench-YYYYMMDD-HHMM.html
set -euo pipefail

PROCESSORS=8
BENCHTIME=2

usage() {
  cat <<'EOF'
Usage: run_sdk_bench.sh [-n PROCESSORS] [-t SECONDS]

Run the filestream encoding SDK benchmark and post-process results.

Options:
  -n PROCESSORS   GOMAXPROCS for the benchmark (default: 8)
  -t SECONDS      -benchtime duration per op (default: 2)
  -h              Show this help

Writes to ~/code/benchmarks:
  sdk-bench-YYYYMMDD-HHMM.log
  sdk-bench-YYYYMMDD-HHMM.csv
  sdk-bench-YYYYMMDD-HHMM.html
EOF
}

while getopts ":n:t:h" opt; do
  case "$opt" in
    n) PROCESSORS="$OPTARG" ;;
    t) BENCHTIME="$OPTARG" ;;
    h)
      usage
      exit 0
      ;;
    \?)
      echo "Unknown option: -$OPTARG" >&2
      usage >&2
      exit 1
      ;;
    :)
      echo "Option -$OPTARG requires an argument." >&2
      usage >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
OUTPUT_DIR="${HOME}/code/benchmarks"
STAMP="$(date +%Y%m%d-%H%M)"
BASENAME="sdk-bench-${STAMP}"
LOG="${OUTPUT_DIR}/${BASENAME}.log"
CSV="${OUTPUT_DIR}/${BASENAME}.csv"
HTML="${OUTPUT_DIR}/${BASENAME}.html"

mkdir -p "$OUTPUT_DIR"

echo "Running SDK benchmark: GOMAXPROCS=${PROCESSORS}, benchtime=${BENCHTIME}s" >&2
echo "Log: ${LOG}" >&2

(
  cd "$CORE_DIR"
  GOMAXPROCS="$PROCESSORS" go test ./internal/filestream/encodingbench \
    -run '^$' \
    -bench 'BenchmarkEncode$' \
    -benchmem \
    -benchtime="${BENCHTIME}s"
) | tee "$LOG"

python3 "${SCRIPT_DIR}/parse_bench.py" "$LOG" -o "$CSV"
python3 "${SCRIPT_DIR}/build_dashboard.py" "$CSV" -o "$HTML"

echo "Done." >&2
echo "  log:  ${LOG}" >&2
echo "  csv:  ${CSV}" >&2
echo "  html: ${HTML}" >&2
