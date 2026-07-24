# Filestream encoding benchmark

This benchmark measures complete history-only filestream request envelopes,
starting from prebuilt transaction-log `HistoryRecord` messages. Each
transport is a `<payload_format>/<envelope_format>` combination — payload
formats are `jsonl`, `row_proto`, and `column_proto`; envelope formats are
`json` (the production-shaped JSON envelope, protobuf payloads base64-encoded)
and `native` (payload messages nested directly in a protobuf envelope). Five
combinations are benchmarked:

- `jsonl/json` — legacy extended JSONL inside the production JSON envelope;
- `row_proto/json` — one base64-encoded row protobuf per JSON `content` entry;
- `row_proto/native` — row protobuf messages nested in a protobuf envelope;
- `column_proto/json` — one base64-encoded columnar protobuf batch in a JSON envelope;
- `column_proto/native` — a columnar protobuf batch nested in a protobuf envelope.

Every transport runs from both `json_value` and `typed_value`
`HistoryRecord` fixtures. Fixture construction is outside the timed region;
history conversion, inner serialization, base64, and outer-envelope encoding
are timed.

Decode benchmarks and decode correctness tests live in Gorilla; this package
owns encode benchmarks and exports a fixture corpus for backend decode tests.

Run correctness tests and a quick benchmark smoke test from `core/`:

```sh
go test ./internal/filestream/encodingbench
go test ./internal/filestream/encodingbench -run '^$' -bench 'Benchmark(Encode|Compress)$' -benchmem -benchtime=1x
```

For stable SDK-side measurements suitable for `benchstat`, use a fixed
multi-second duration and repeated samples:

```sh
go test ./internal/filestream/encodingbench \
  -run '^$' \
  -bench 'Benchmark(Encode|Compress)$' \
  -benchmem \
  -benchtime=3s \
  -count=10 \
  | tee encodingbench.txt
```

Compression timing is separate and operates on the complete envelope:

```sh
go test ./internal/filestream/encodingbench \
  -run '^$' \
  -bench BenchmarkCompress \
  -benchmem \
  -benchtime=3s \
  -count=10
```

Encode results include complete envelope bytes, inner body bytes, envelope
expansion, gzip-1/gzip-6 sizes and ratios, operations per second, and rows/cells
per operation. Compression results also report operations per second independently
of byte throughput.

Export the fixture corpus consumed by Gorilla decode benchmarks:

```sh
go run ./internal/filestream/encodingbench/cmd/exportfixtures
```

Regenerate `filestream.pb.go` after changing the benchmark-only schema:

```sh
protoc -I . -I .. \
  --go_out=. \
  --go_opt=paths=source_relative \
  --go_opt=Mwandb/proto/wandb_internal.proto=github.com/wandb/wandb/core/pkg/service_go_proto \
  internal/filestream/encodingbench/filestream.proto
```
