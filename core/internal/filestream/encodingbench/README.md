# Filestream encoding benchmark

This benchmark measures complete history-only filestream request envelopes,
starting from prebuilt transaction-log `HistoryRecord` messages. It compares
five transports:

- legacy extended JSONL inside the production-shaped JSON envelope;
- one base64-encoded row protobuf per JSON `content` entry;
- row protobuf messages nested directly in a protobuf envelope;
- one base64-encoded columnar protobuf batch in a JSON envelope;
- a columnar protobuf batch nested directly in a protobuf envelope.

Every transport runs from both `value_json_only` and `typed_only`
`HistoryRecord` fixtures. Fixture construction is outside the timed region;
history conversion, inner serialization, base64, and outer-envelope encoding
are timed.

Run correctness tests and a quick benchmark smoke test from `core/`:

```sh
go test ./internal/filestream/encodingbench
go test ./internal/filestream/encodingbench -run '^$' -bench 'Benchmark(Encode|Decode)$' -benchmem -benchtime=1x
```

For stable SDK-side measurements suitable for `benchstat`, use a fixed
multi-second duration and repeated samples:

```sh
go test ./internal/filestream/encodingbench \
  -run '^$' \
  -bench 'Benchmark(Encode|Decode)$' \
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
per operation. Decode and compression results also report operations per second
independently of byte throughput.

Regenerate `column.pb.go` after changing the benchmark-only schema:

```sh
protoc -I . -I .. \
  --go_out=. \
  --go_opt=paths=source_relative \
  --go_opt=Mwandb/proto/wandb_internal.proto=github.com/wandb/wandb/core/pkg/service_go_proto \
  internal/filestream/encodingbench/column.proto
```
