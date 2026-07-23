# Gorilla backend benchmark plan

This plan evaluates the backend cost of the three initial history/event
representations:

1. legacy row-oriented extended JSONL;
2. length-delimited row-oriented `HistoryRecord` protobuf messages;
3. column-oriented protobuf batches.

The SDK harness in this directory measures the batch body. Backend benchmarks
should consume the same generated payloads and expected-result manifest so the
two sides use identical rows, type mixes, batch sizes, and edge cases.

## Current Gorilla seams

The backend currently performs work in multiple consumers of a filestream
update:

- `services/gorilla/domain/runupdates/flat/filestream_preprocess.go` calls
  `gorilla.ParseHistoryRows` for history lines. This is CPU-heavy parsing done
  before the run metadata transaction.
- `services/gorilla/domain/runupdates/flat/flat_run_fields_updater.go` calls
  `AppendKeysInfoDeserialized` in the batched run update. This performs history
  flattening, type aggregation, `_step` handling, and out-of-order-row logic.
- `services/gorilla/domain/history/run_update_batcher.go` keeps raw chunks and
  builds lazy `KVIterator`s. When an iterator is consumed,
  `services/gorilla/domain/history/history.go:parseKVMap` decodes JSON,
  flattens metrics, cleans values, and constructs `metrics.KVMap` rows.

Consequently, the benchmark must measure both the run-metadata consumer and the
history-storage consumer. Measuring only HTTP request decoding would omit the
main repeated JSON work.

## Fixture and protocol setup

1. Extend the SDK harness with a fixture command that writes, for each
   workload and batch size:
   - legacy JSONL bytes;
   - row-protobuf bytes;
   - column-protobuf bytes;
   - a manifest containing row count, cell count, key/type counts, byte sizes,
     and a canonical expected result.
2. Keep the column-protobuf schema versioned and shared with Gorilla when the
   backend decoder is implemented. Do not duplicate independently evolving
   schemas in the two repositories.
3. Include a manifest checksum and schema/format version in every fixture.
4. Preserve privacy: fixtures contain deterministic synthetic values only.
   Any later real-shape corpus must retain distributions and lengths without
   retaining customer keys or values.

## Benchmark layers

### 1. Decode-only microbenchmarks

Add Gorilla Go benchmarks for each format that decode one batch into a typed
row/cell sink. Record:

- ns/op and rows/sec;
- cells/sec;
- bytes/sec;
- allocations/op and bytes allocated/op;
- malformed/truncated payload error cost.

The typed sink should not allocate `map[string]any` unless that is the specific
variant being measured. Run a second variant that produces the existing
`metrics.KVMap` representation for a direct apples-to-apples phase-1 backend
implementation.

### 2. Keys-info path

Benchmark the work needed by the flat run-fields updater:

- legacy: `ParseHistoryRows` followed by `AppendKeysInfoDeserialized`;
- row protobuf: decode to equivalent typed rows, adapt to the existing
  keys-info input, then aggregate;
- column protobuf: decode directly into typed key/value observations, then
  aggregate without JSON materialization where possible.

Measure parsing/adaptation separately from the aggregation itself. Include
`_step`, `_timestamp`, `_runtime`, nested objects, type changes, and
out-of-order rows. Verify that all formats produce identical keys info,
last-step, type counts, and out-of-order behavior.

### 3. History-storage conversion

Benchmark conversion into the history storage interface:

- legacy: `BatchItemsToWritePayload` plus complete iterator drain;
- row protobuf: decode and build equivalent `metrics.KVMap` rows;
- column protobuf: decode into typed rows and build `VariantValue` values.

Iterator draining is mandatory. `BatchItemsToWritePayload` is lazy, so timing
only payload construction would not include the existing JSON parsing and
flattening work.

Use a no-op storage engine that consumes every row and value. This isolates
decode/conversion CPU and allocation pressure from database latency.

### 4. Run-update transaction path

Benchmark a production-shaped `UpdateRunForFileStream` flow with deterministic
run metadata and a fake run store:

- request decode and decompression;
- history/event decode;
- preprocessing;
- keys-info merge;
- transaction callback duration;
- queue/batcher enqueue and flush;
- complete `WritePayload` consumption.

Report preprocessing time separately from transaction time. The current flat
path intentionally moves JSON parsing before the transaction, while keys-info
merging remains in the transaction callback.

### 5. Storage-engine confirmation

Run the winning two implementations against a local history storage engine
after the no-op benchmarks. Use the existing history storage benchmark
infrastructure where possible, but add an ingest/write mode rather than
measuring reads only. Compare:

- one run, sequential batches;
- many independent runs in parallel;
- repeated updates to one run with 1, 8, and 32 producers;
- small batches and batches near the filestream request limit.

The storage-engine phase confirms that codec gains survive batching and writes;
it should not be used as the only signal because storage latency can hide
conversion regressions.

## Workload matrix

Use the SDK harness workloads unchanged:

- tiny single-row batches;
- dense numeric rows;
- sparse mixed rows with a large key space;
- wide mixed rows;
- nested JSON/array fallback values;
- system-metric-heavy rows.

Run at 1, 16, 128, and 1,024 rows, plus size-driven batches near 1 MiB and
10 MiB. Include nulls, strings, booleans, finite numbers, NaN, positive and
negative infinity, Unicode, duplicate/churning keys, malformed JSON bytes,
unknown protobuf kinds, invalid dictionary indexes, and truncated payloads.

## Correctness requirements

For every fixture, compare the final normalized result with the legacy path:

- row count and ordering;
- flattened metric keys;
- scalar values and type classification;
- null and non-finite-number semantics;
- opaque JSON values;
- keys-info type counts and last-step;
- out-of-order row handling;
- history offsets and event offsets.

Malformed typed requests must fail with bounded resource use and a clear
validation error. Unknown fields may be ignored only where the selected schema
policy explicitly permits it; unknown value kinds and invalid indexes must be
rejected.

## Metrics and profiling

Collect:

- p50/p95 latency for load tests;
- ns/op, rows/sec, cells/sec, and bytes/sec;
- allocations/op and peak RSS;
- request bytes before/after compression;
- JSON parse, typed decode, flattening, keys-info, and storage-conversion
  timings;
- transaction duration and lock/queue wait time;
- error and fallback counts.

Use Go `-benchmem`, repeated runs with fixed hardware and `GOMAXPROCS`,
`benchstat`, CPU/memory profiles, and a concurrency load test. Keep raw metric
names and values out of logs and telemetry.

## Decision gates

A typed backend path advances only if it:

- produces semantic parity with the legacy path;
- rejects malformed payloads safely;
- lowers weighted decode/conversion CPU by at least 20%;
- does not regress small-batch p95 latency;
- preserves or improves error rate and offline/queued update behavior.

Select the implementation using a declared score over CPU, allocations,
transaction time, wire bytes, and operational complexity. Keep the legacy
decoder available as a per-request fallback throughout the experiment.

## Deliverables

- shared fixture generator and versioned fixture corpus;
- Gorilla decode, keys-info, conversion, transaction, and storage benchmarks;
- correctness and malformed-input tests;
- CPU/memory profiles and reproducible benchmark commands;
- a report comparing all three formats by workload and backend stage;
- an ADR recommending a format, documenting fallback behavior and unresolved
  direct-to-`VariantValue` work.
