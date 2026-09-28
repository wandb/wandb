# Typed system metrics

Design, revision 2, 2026-09-26. The schema is `wandb/proto/wandb_system_metrics.proto`.

Continuation of the Typed History program (SDK: Geoff's "Typed History, SDK Design"; server: `domain/filestream/ingest/typed_history_ingest.md`, wandb/core#50294, #51759, #52514). Facts below were verified in wandb/wandb `main`, wandb/core `master` and the xpu crate; several come from a parallel investigation on 2026-09-26 and were re-checked.

## Summary

System metrics become one typed proto message, `SystemMetricsRecord`, that spells out every quantity wandb-core and wandb-xpu collect: host CPU, memory, swap, disks, network, power; the monitored process tree; accelerators with a vendor-neutral core and NVIDIA, AMD, TPU and Trainium extensions; TPU runtime distributions; Trainium host memory; and a generic escape hatch for OpenMetrics scrapes and future vendor or user metrics. Attribution (writer id, label) and device identity (type, index, uuid, PCI bus id, host, source) are fields.

The proto is the only catalog. Every leaf field carries a `MetricInfo` option with unit, title, kind, chart range and the legacy filestream key templates. One generated function turns a record into today's `system.*` JSON line, so stored key strings do not change and no consumer parses them. Adding a metric is a proto change that regenerates Go, Rust, Python and, in phase 2, TypeScript. A metric without a chart cannot happen silently.

Two phases:

- **Phase 1, SDK only, no wire change.** The record is the transaction log format, the wandb-xpu gRPC response, the monitor's sample type, and what leet, LocalApi and the in-memory buffer read. Filestream renders legacy JSON lines from it. Ships behind a golden test that pins today's keys.
- **Phase 2, server.** Planned here, not implemented. The server accepts the record on the filestream, flattens at ingress into the typed batch it already has (#52514), applies the writer-label rename in one place, stores the schema path beside each key, serves the schema to the web app, and the panel bank is generated from it. A typed store with a writer dimension is the end state and a separate migration.

User-posted events are a separate project (Notion "Event Overlays": sparse, step-anchored annotations with a title, message, labels and URL, their own log-based store). They share nothing with this design beyond attribution and offline persistence.

## Transaction log compatibility

Only the new record is written. Readers keep the `StatsRecord` path, so `wandb sync`, leet and the inspector read old logs unchanged. An older wandb reading a newer log sees an unknown record type, the same as for every record type added before (`Record.environment` in 2025, `Record.output_logger` in 2026); the `.wandb` version byte is not bumped for a system-metrics-only change. Servers that do not accept the typed record, which is every server until phase 2, receive the same JSON lines as today, rendered from the record.

## What changed since revision 1

Revision 1 kept string keys as identity and hung a per-key descriptor beside them. The string stayed the join key, the read-time `system.` to `system/` rewrite stayed, and rows without descriptors fell back to regex tables. It also merged custom events into the same record, and it overstated what exists: it called the carrier "ready on both ends" when the server's filestream handler decodes JSON only. This revision uses a closed schema with an escape hatch, keeps events out, and moves all server work to a planned phase 2 with its real preconditions.

## Where we are

**Producers** build string keys by hand at about 40 `format!` sites in `gpu_nvidia.rs`, 7 in `gpu_amd.rs`, 24 literals in `gpu_apple.rs`, 18 templates in `tpu_libtpu.rs`, and `Sprintf` calls in `system.go`, `trainium.go`, `dcgm_exporter.go`, `openmetrics.go`. Values travel as `value_json` strings. `filestream/updatestats.go` parses each one back, prefixes `system.`, adds `_wandb`, `_timestamp`, `_runtime`. `monitor.go:501` appends `/l:<x_label>` to every key; `dcgm_exporter.go:353` appends `/l:<node>`; in shared mode a DCGM key gets both. Attribution and a device dimension share one suffix.

**Consumers parse it back.** The web app has three regex tables (`util/panels.ts` 85, `util/plotHelpers/prettifyMetricName.ts` 87, `util/isAutoPanel.ts` about 60). leet has 102 regexes plus `ExtractBaseKey` and `ExtractSeriesName`, with two byte-identical copies in the Rust ports (leet-rs, leet-gpui) and a test pinning the row count. The server rewrites `system.` to `system/` at nine call sites and back again in the parquet exporter. Launch's eventsink and the metric-threshold triggers match key strings too.

**They have drifted.** Emitted today with no chart anywhere: `fanSpeed`, AMD `memoryReadWriteActivity` and `memoryOverDrive`, DCGM `totalEnergyConsumption`, `memoryTemp`, `maxOpTemp`, `memoryMaxOpTemp`, `memoryTotal`, `memoryFree`. #11528 renamed the TPU memory keys in April and the web app still matches the old names. leet drops every `openmetrics.*` key. leet keeps six IPU rows for a collector deleted in 2025. Seven commits changed the visible key set in 24 months, in bursts when a vendor is onboarded. WB-39486: our own agent used `system.` where the UI wanted `system/`.

**The same key means different things depending on who produced it.** NVML GPM reports `pcieTxBytes` in MiB/s, DCGM in bytes, leet charts GiB/s, the web app says "Bytes". `smActive` is a 0 to 100 percent from wandb-xpu and a 0 to 1 ratio from the Go DCGM exporter under the same key. AMD `temp` reads the memory sensor, Apple `gpu` is a frequency-weighted residency. GPM and DCGM can both be active on Hopper and their keys collide; the last write wins. AMD writes 0.0 for a missing field. `run._system_metrics` drops every whole-number sample because the buffer only accepts float64 after JSON parsing.

**What the server has.** wandb/core#52514 (2026-09-23, ramp off) parses events once at ingress into `ingest.Batch` with `_timestamp` as the sequence key and ships it typed to FRFU, RSA, the history store, the metric observer and BT v2. Keys are still strings, and every store keys series by that string: BT v3 row keys hash `entity:project:run:system:<key>`, ClickHouse and RSA use `field_key`, parquet exports use the key as the column name. The filestream handler decodes JSON only and never reads `Content-Type`; a protobuf body is a 400. The SDK's typed wire schema (#12805) has no server decoder yet; wandb/core#53963 (open) vendors it with drift checks and says nothing decodes it. The web app already generates TypeScript from proto (`@bufbuild/protoc-gen-es`, history Connect API), so consuming a schema is not new tooling.

**Asks.** WB-39271 (Graphcore wants a vendor path), WB-23848 (GPU-only collection and reads), GH 10358, 5857, 7470, 1133 (choose what is collected), the shared-mode label hack, and the label lost on `wandb sync` (the syncer has a fresh ClientID and no settings).

## The schema

Full text in `wandb/proto/wandb_system_metrics.proto`. Shape:

```
SystemMetricsRecord
  timestamp, writer_id, label
  host          HostMetrics          cpu{cores[], apple}, memory{apple}, swap, disk_usage[], disk_io[], network, power
  process       ProcessMetrics       cpu_percent, rss_bytes, memory_percent, threads
  accelerators  AcceleratorMetrics[] type, index, uuid, host, source, in_use_by_process, pci_bus_id,
                                     utilization, memory activity / used / total, temperature, power, power limit,
                                     clock, fan, energy, process_memory_used,
                                     oneof ext { nvidia | amd | tpu | trainium }
  tpu_runtime   TpuRuntimeMetrics    distributions[] {kind, label, mean, p50..p999, histogram}, hlo_queue_size[]
  trainium_host TrainiumHostMetrics  host and device totals, host breakdown
  generic       GenericMetric[]      source, name, labels[], kind, unit, help, value
```

82 annotated leaf fields, 98 legacy key templates, 6 accelerator types.

### Principles

- **Closed core, open tail.** Everything a first-party collector emits is a named field. OpenMetrics scrapes, vendor collectors and later user-pushed metrics go through `GenericMetric` (source, name, labels, kind, unit, value) and get a generic chart per (source, name) with one series per label set. TPU HLO program names and OpenMetrics labels are unbounded, so the tail is a requirement, not a fallback.
- **The proto is the catalog.** `MetricInfo` on each leaf carries unit (UCUM), title, kind (gauge or counter), chart range and legacy templates. The Go legacy renderer, the Rust emitters, the phase 2 server flatten and the phase 2 panel bank all read the same descriptor through reflection. There is no other list.
- **Vendor-neutral core, vendor extensions.** Only three key suffixes are shared literally across GPU vendors today (`gpu`, `temp`, `powerWatts`); about seven concepts are shared semantically. `AcceleratorMetrics` holds those seven (utilization, memory activity, memory used and total, temperature, power, power percent and limit, clock, fan, energy); vendor specifics live in `oneof ext`. This is what makes one cross-vendor "Accelerator utilization" panel possible.
- **Identity and attribution are fields.** `type`, `index`, `uuid`, `pci_bus_id`, `host`, `source` on the accelerator; `writer_id` and `label` on the record, stored in the log so `wandb sync` replays them. `source` matters: it separates GPM from DCGM on the same device and selects source-specific legacy keys.
- **Units are normalized at the producer.** Bytes, bytes per second, percent, MHz, watts, Celsius, seconds, joules. Where legacy lines used another scale (`MiBy`, `GiBy`, `mJ`), the template says so and the renderer converts.
- **Presence is explicit.** Leaves are `optional`; absent is not zero. A partial record from one collector is a normal record.
- **Static facts stay in `EnvironmentRecord`.** Device name, memory total, CUDA cores, architecture, AMD overdrive settings. The sample references the device by type and index, and by uuid when the vendor has one.

### Legacy key templates

A template is a string with placeholders (`{index}`, `{path}`, `{device}`, `{source}`, `{name}`, `{series}`, `{label}`, `{stat}`). The renderer prefixes `system.`, appends `/l:<host>` for accelerators with `host` set, and `/l:<label>` when the writer label is set. Where the same quantity had different legacy names, the field lists one template per accelerator type or per source:

```proto
optional double utilization_percent = 10 [(metric) = {
  unit: "%", display: "Utilization", range_min: 0, range_max: 100, legacy_process_copy: true,
  legacy: [
    {accelerator_type: NVIDIA_GPU, template: "gpu.{index}.gpu"},
    {accelerator_type: GOOGLE_TPU, template: "tpu.{index}.tensorcoreUtilization"},
    {accelerator_type: AWS_TRAINIUM, template: "trn.{index}.neuroncore_utilization"}]}];

optional uint64 memory_used_bytes = 13 [(metric) = {
  unit: "By", display: "Memory Used", legacy_process_copy: true,
  legacy: [
    {accelerator_type: NVIDIA_GPU, source: "nvml", template: "gpu.{index}.memoryAllocatedBytes"},
    {accelerator_type: NVIDIA_GPU, source: "dcgm-exporter", template: "gpu.{index}.memoryUsed", unit: "MiBy"},
    {accelerator_type: GOOGLE_TPU, template: "tpu.{index}.hbmCapacityUsage"}]}];
```

`legacy_process_copy` marks the eight fields the NVIDIA sampler repeats under `gpu.process.{index}.*` when the monitored process uses the device. Those were always copies of the device values; the record carries one `in_use_by_process` flag, and a new typed-only `process_memory_used_bytes` is the first real per-process number. A field with no matching template has no legacy key and is visible on the typed path only.

The templates exist because today's keys are irregular (`cpu`, `memory_percent`, `disk./.usagePercent`, `system.system.powerWatts`, TPU stat suffixes). If key names are regularized at 1.0 the templates go away and the flatten becomes a mechanical path walk. See decisions.

### What the typed path fixes by construction

- Whole-number samples dropped by the buffer, and NaN turning into JSON null: typed values.
- `smActive` ratio vs percent, `pcieTxBytes` MiB/s vs bytes: one unit per field, converted at the producer.
- Zero meaning missing on AMD and Apple: presence.
- DCGM `/l:node` plus `/l:x_label` double suffix: `host` and `label` are two fields.
- TPU key shape depending on which backend answered: the label is a field; the gRPC histogram buckets are kept instead of interpolated and thrown away.
- GPM and DCGM colliding on one device: two entries with different `source`.
- Label lost on `wandb sync`: attribution is in the log record.
- Device index meaning different things per producer: `uuid` and `pci_bus_id` beside `index`.

The legacy renderer reproduces today's keys exactly. For values it emits the legacy unit where today's producers agreed (MiB, GB, mJ) and the majority convention where they disagreed (percent for ratios, bytes per second for throughput, which is what the web app titles assume). Those two value changes are intentional and listed in the changelog.

### Typed-only, legacy-only, redundant

Typed-only after phase 1: NVML `memory_total_bytes` (xpu keeps it internal today), `uuid`, `pci_bus_id`, `source`, `process_memory_used_bytes`, TPU histograms, and the label and host fields themselves. Legacy-only: per-core CPU (`cpu.N.cpu_percent`, Python SDK era, never emitted by wandb-core; a field is reserved for an opt-in) and IPU (deleted 2025, not modeled). Off by default in code and modeled anyway: `graphicsClock`, `encoderUtilization`, the five PCIe link fields (#9125).

Redundant and visible now: on macOS both `system.go` and the Apple sampler report memory (`memory_percent`, `memory.used_percent`); the draft models both because both are collected. AMD `memoryOverDrive` is a static setting already in `GpuAmdInfo`. DCGM `memoryFree` is total minus used. Candidates to drop at 1.0.

## Phase 1: SDK

No wire change. Everything below is inside wandb-core, wandb-xpu and the Python client. wandb-xpu ships in the same wheel as wandb-core and is resolved next to it, so the gRPC contract changes in lockstep with no negotiation.

1. **Proto.** `wandb/proto/wandb_system_metrics.proto` and `Record.system_metrics = 28`, generated for Go, Python and Rust. `StatsRecord` stays readable, no longer written once the producers switch.
2. **Producers.** `monitor.Resource.Sample()` returns `*SystemMetricsRecord`. `system.go` fills `host` and `process`; `dcgm_exporter.go` fills `accelerators` with `host` and `source = "dcgm-exporter"` and scales ratios to percent; Trainium fills `accelerators` (one per NeuronCore) and `trainium_host`; OpenMetrics fills `generic` with labels, kind, unit and help (it drops all three today). wandb-xpu builds the NVIDIA, AMD, Apple and TPU parts from its samplers; the samplers already have typed structs (`GpuStats`, `Metrics`, `SocInfo`, the TPU `MetricSpec` registry, `GpuMetricAvailability`), so this is mostly deleting the string formatting. `GetMetadata` returns the static structs directly instead of running a full sample and reading `_gpu.{i}.name` keys back.
3. **Legacy renderer.** One Go function, `systemmetrics.RenderLegacyLine(record, startTime)`, walks the record with protobuf reflection, reads `MetricInfo`, substitutes placeholders, converts legacy units, applies the process copy and the two `/l:` rules, and emits today's JSON line with `_wandb`, `_timestamp`, `_runtime` (`_runtime` is read back by resume, so it stays). `filestream.StatsUpdate` calls it; so do the buffer's legacy view and the LocalApi rows, so Python keeps seeing one spelling per surface instead of a fourth. `monitor.go:501` and `dcgm_exporter.go:343-355` are deleted.
4. **Golden test.** A fixture record per producer, rendered, compared with the keys the current collectors emit for the same inputs. Any template typo fails CI. The fixture is the inventory for review.
5. **Readers.** leet's `ParseStats` and its regex table, `monitor.Buffer` and `GetSystemMetricsResponse` (typed values, attribution), and LocalApi read the record. Charts group by field path and vendor type, series by index, host and label, titles from `display` and `unit`. The regex table stays for `.wandb` files written before this lands, detected by record type, and stops growing. The Rust ports get the same treatment when they catch up.
6. **Sequencing with PR 12767** (LocalApi system metrics, open): it adds a second legacy renderer with `system.` keys and a docstring that says they match the UI (which uses `system/`). Either it lands on the shared renderer or after phase 1.
7. **Collection spec.** `Settings.system_metrics` with `include` and `exclude` lists of field paths with globs (`accelerators.*`, `host.disk_*`, `accelerators.nvidia.pipe_*`) plus `interval_s`. Filtering by field path is a reflection walk, before sampling where the collector supports it (skip the NVML call) and after otherwise. `x_stats_open_metrics_filters` keeps working as the filter for `generic`. The per-collector `x_stats_*` toggles become aliases.
8. **Label.** `x_label` becomes `Settings.label` and lands in the record. Precedent: console logs moved the label from a text prefix to a JSON field behind `ServerFeature_STRUCTURED_CONSOLE_LOGS`.

Phase 1 kills `StatsRecord` and `value_json`; the JSON re-parse in `updatestats.go`, `buffer.go` and leet; two `/l:` producers; string formatting in four Rust samplers and four Go collectors; xpu parsing its own keys; the leet regex table for new logs. It does not change bytes on the wire, stored keys, or the web app.

## Phase 2: server (planned, not implemented)

Goal: the server understands `SystemMetricsRecord`, stores identity beside the key, serves the schema, and the web app stops parsing. Consumers first, wire last, the discipline of the typed history rollout doc.

### 2a. Accept the record on the filestream

```proto
message FileStreamUpload {
  // ...
  // Typed system metrics. Replaces "wandb-events.jsonl" in `files`; same 400
  // rule as `history`.
  repeated SystemMetricsRecord system_metrics = 7;
}
```

Row-shaped is right here: a request carries a handful of records per writer (one per collector per 15 s), an 8-GPU host is a few KB of tags and doubles, and the record is already the log format. The columnar batch remains the server's internal representation.

Preconditions, all missing today:

- A filestream body decoder that dispatches on `Content-Type`. The handler decodes JSON only; the typed history transport (`application/vnd.wandb.filestream.v1+protobuf`, `FILESTREAM_PROTO_V1`) is the same precondition and should land first. wandb/core#53963 vendors the SDK schema but decodes nothing.
- A `ServerFeature` (`TYPED_SYSTEM_METRICS_UPLOAD`) the SDK checks through `featurechecker`; without it the SDK renders lines. Proto3 drops unknown fields silently, and an old server answers a protobuf body with 400, not 415, so the SDK must not probe by sending.
- Every new request field classified in `TestFileStreamWireFieldsClassified`; the request struct is the queue message, so fields reach out-of-repo `run-updates-v2` readers (DPE).
- The system-test backend spy reads `wandb-events.jsonl` lines only and needs typed-chunk support.

Ingress flatten: `ingest.FromSystemMetrics(records)` walks each record with the same reflection as the SDK renderer (options live in the proto, so both sides derive the same keys from one source) and produces the `ingest.Batch` that `normalizeEvents` produces today, `_timestamp` in the sequence column, `_runtime` as a cell. Everything downstream of `Chunk.Batch` (FRFU, RSA, history store, metric observer, BT v2, sync) is typed-aware since #52514 and does not change. The `_wandb` marker is implied for typed chunks.

Label rename: when `label` is set the flatten emits keys with `/l:<label>`, the same rule the SDK renderer applies today. This is the single producer of that encoding for new SDKs; it is deleted in 2d.

Rollout: decoder dark, then a per-project ramp mirroring `run_updater_typed_events`. Rollback is the SDK falling back to lines when the feature is withdrawn.

### 2b. Identity beside the key

The system-metrics field table (RSA `column = 'system_metrics'`, FRFU's MySQL twin) gains the schema path for each key, written by the fold from the flatten's key-to-path map. `systemMetricsKeyInfos` in `history.go` synthesizes events keys-info from that table; `KeyInfo` gains `path` (for example `accelerators.temperature_c` with `type = NVIDIA_GPU`, `index`, `host`, `label`). `historyKeys` serves it. `CleanSystemMetricName` still runs on the key string for compatibility, but the web app no longer needs the key to mean anything.

The ignore test holds: a consumer that ignores `path` gets correct values and worse titles; the rename runs before any queue hop so no consumer can ignore `label` into wrong data.

### 2c. Serve the schema, generate the panel bank

The web app compiles `wandb_system_metrics.proto` with `protoc-gen-es`, as it compiles `services/gorilla/api/history/history.proto` today. Its panel bank walks the proto descriptor: one panel per leaf field (or per `display` when several vendors share it), series from `type`, `index`, `host`, `label`, title from `display` and `unit`, range from `range_min` and `range_max`, generic metrics through one chart per (source, name). The three regex tables are frozen for runs whose keys-info has no `path`. Launch's eventsink and the triggers get the same `path` and stop matching strings.

Whether the schema is a vendored proto or a `serverInfo` field generated by the server is a phase 2 decision; the option data is the same either way.

### 2d. Typed store and writer dimension

The end state: system metrics stored in typed columns (`writer_id`, `label`, `type`, `index`, `host`, field) rather than string keys, read through the history Connect API the web app already uses for columnar fetches (it excludes system metrics today). The `/l:` rename is deleted, cross-writer and cross-vendor panels become queries, and `system.` versus `system/` stops existing.

Honest cost: the key string is the physical series identity in BT v3 (row-key hash), the column name in parquet, and `field_key` in ClickHouse, RSA and MySQL. Adding a writer or device dimension means new row-key formats and columns in every store, the parquet layout and the GraphQL types. This is the one-stream-per-writer convergence from the SDK 1.0 plan and belongs with the events store work, not with 2a to 2c.

## Adding a metric, before and after

Before: add a format string in Rust or Go; add a regex to `panels.ts`, another to `prettifyMetricName.ts`, another to `isAutoPanel.ts`, another to leet and its two Rust copies; hope nobody forgets one. Nine keys have no chart today and the TPU rename went unnoticed for five months.

After: add a field with a `MetricInfo` option in one proto; regenerate. The legacy renderer, the golden fixture, leet, the server flatten and the panel bank pick it up through reflection. A field without an option fails a proto lint. Removing one means `reserved`, the same as any proto.

## Decisions

- **Closed schema with an escape hatch, not descriptors as data.** Descriptors left identity a string and drift a runtime condition, and a descriptor keyed by the key string cannot be one constant when the same key carries producer-dependent units. The proto makes drift a compile error. Vendors and users still have `GenericMetric`.
- **System metrics and user events are separate records.** Dense periodic samples with a known schema want a struct; sparse annotations want a row with a title and attributes. They may share the server's timestamp-sequenced transport; they share no model.
- **Row-shaped record on the wire, columnar batch inside the server.** Per-writer request volume is tiny; the batch's dictionary win is for history at scale. The server converts once at ingress.
- **Stored keys stay byte-identical until 1.0.** They are pinned by saved panels and reports (`system/`), triggers (exact `system/` match), parquet column names, BT v3 row-key hashes, `Project.fields` paths and run filters, public API rows (`system.`) and the raw GCS archive. Templates in the proto, golden test in CI. At 1.0 (December, the last breaking window per the SDK 1.0 plan) decide whether new runs get regular keys derived from the path; if yes, delete the 98 templates, `legacy_series_index` and the Apple memory duplicate, and keep the frozen regex path for old runs.
- **Values are normalized even on the legacy path where producers disagreed.** Percent for ratios, bytes per second for throughput. Two intentional visible changes; the alternative is preserving a mismatch the charts already mislabel.
- **`in_use_by_process` replaces eight duplicated values.** Same information, one flag, plus one real per-process field.
- **`source` on the accelerator.** Needed for two legacy names (NVML versus DCGM memory), for the GPM and DCGM collision, and it answers "why are there no GPU metrics" with a value rather than an absence.
- **Static device facts stay in `EnvironmentRecord`.** Its own gaps (brand collected and dropped, driver version never collected, `cuda_version` is the driver's, non-primary writers' metadata never reaching the server) are real but a separate cleanup.

Rejected: OTLP metrics on the wire (row-shaped, no dictionary, large dependency; we borrow its vocabulary); structured keys in the string (`gpu.temp{gpu=0}` breaks every saved panel and puts braces into GraphQL filters); `define_metric` and config `_wandb.m` as the schema store (config is the whale blob the server already trims); server-interned metric ids on the wire (a storage concern, assignable later from the path); a hand-maintained catalog file (the proto options are the catalog, adjacent to the fields they describe).

## Open questions

1. **Sequence column for events.** `MetricsBatch.seqs` is `sint64`; the SDK's `_timestamp` is a float of seconds, so the server never promotes it and `seqs` stays empty for events. For 2a propose nanoseconds in `seqs` with float `_timestamp` derived for legacy readers. Server team's call.
2. **Typed filestream transport.** 2a depends on the server dispatching on `Content-Type`; that is the typed history transport's first server stage. Who owns it and when.
3. **Schema delivery to the web app** (2c): vendored proto or served descriptor.
4. **Key regularization at 1.0.** Yes removes 98 templates and two compat fields; no keeps scripts and reports stable across the boundary. Recommend yes for new runs, with a documented mapping.
5. **Cardinality defaults.** Per-device disk I/O and TPU program labels are the unbounded ones (WB-23848 was 208 CPUs). The collection spec makes caps expressible; pick defaults.
6. **AMD temperature sensor.** Keep the memory sensor rocm-smi reads today, or switch to edge or junction. Behavior change either way.
7. **wandb-core self-metrics** from the resource-envelope design belong in this record (a `wandb` submessage under `host`). Add when that work lands.
8. **Public API reads.** `run.history(stream="system", keys=[...])` (the refusal is SDK code) and exposing `path` through `Run.history_keys` follow 2b.
9. **Can GPM and DCGM profiling run at once on Hopper?** If yes, today one record carries 12 duplicate keys with different units. Needs a hardware check.

## Appendix: producer inventory

| Producer | Today | Typed home |
|---|---|---|
| `monitor/system.go` (gopsutil, cgroup) | `cpu`, `proc.cpu.threads`, `proc.memory.rssMB`, `proc.memory.percent`, `proc.memory.availableMB`, `memory_percent`, `network.sent/recv`, `disk.<path>.usagePercent/usageGB`, `disk.<dev>.in/out` | `ProcessMetrics`, `HostMetrics.memory`, `.network`, `.disk_usage[]`, `.disk_io[]` |
| xpu `gpu_nvidia.rs` (NVML, GPM) | on by default: `gpu.N.{gpu, memory, memoryAllocated, memoryAllocatedBytes, temp, powerWatts, powerPercent, enforcedPowerLimitWatts, smClock, memoryClock, correctedMemoryErrors, uncorrectedMemoryErrors, fanSpeed}`; GPM on Hopper+: `smActive, smOccupancy, pipeTensorActive, dramActive, pipeFp64Active, pipeFp32Active, pipeFp16Active, pipeTensorHmmaActive, pcieTxBytes, pcieRxBytes, nvlinkTxBytes, nvlinkRxBytes`; off in code: `graphicsClock, encoderUtilization, pcieLinkGen, pcieLinkSpeed, pcieLinkWidth, maxPcieLinkGen, maxPcieLinkWidth`; `gpu.process.N.*` (8 copies); internal `_gpu.N.memoryTotal` | `AcceleratorMetrics{NVIDIA_GPU, source="nvml"}` core + `NvidiaMetrics`; `in_use_by_process` |
| xpu `gpu_nvidia_dcgm.rs` (in-process DCGM) | the 12 GPM names, ratios scaled to percent, byte fields raw | same, `source="dcgm"` |
| Go `dcgm_exporter.go` (Prometheus query) | 23 mapped `DCGM_FI_*` fields incl. `memoryUsed, memoryTotal, memoryFree, memoryTemp, maxOpTemp, memoryMaxOpTemp, totalEnergyConsumption`, ratios raw 0 to 1, `/l:<node>` | same, `source="dcgm-exporter"`, `host` set |
| xpu `gpu_amd.rs` (rocm-smi) | `gpu.N.{gpu, memoryAllocated, memoryReadWriteActivity, memoryOverDrive, temp, powerWatts, powerPercent}`, 0.0 when missing | `AcceleratorMetrics{AMD_GPU}` core + `AmdMetrics` |
| xpu `gpu_apple.rs` (IOReport) | `gpu.0.{gpu, freq, powerWatts, temp}`, `ane.power`, `cpu.{ecpu_percent, ecpu_freq, pcpu_percent, pcpu_freq, avg_temp, powerWatts}`, `memory.{used, used_percent}`, `swap.{used, used_percent}`, `system.powerWatts` | `AcceleratorMetrics{APPLE_GPU}`, `{APPLE_ANE}`, `HostMetrics.cpu.apple`, `.memory.apple`, `.swap`, `.power` |
| xpu `tpu_libtpu.rs` (libtpu SDK, gRPC fallback) | `tpu.N.{tensorcoreUtilization, tensorcoreIdleDuration, dutyCycle, hbmCapacityTotal, hbmCapacityUsage, runtimeHbmUtilization, hbmMemoryUsage, iciLinkHealth, throttleScore}`, `tpu.<dist>[.<label>].<stat>Us`, `tpu.grpcTcpDeliveryRate.<stat>Mbps`, `tpu.hloQueueSize.<label>` | `AcceleratorMetrics{GOOGLE_TPU}` core + `TpuMetrics`; `TpuRuntimeMetrics` |
| `monitor/trainium.go` (neuron-monitor) | `trn.N.neuroncore_utilization`, `trn.N.neuroncore_memory_usage.{constants, model_code, model_shared_scratchpad, runtime_memory, tensors}`, `trn.host_total_memory_usage`, `trn.neuron_device_total_memory_usage`, `trn.host_memory_usage.{application_memory, constants, dma_buffers, tensors}` | `AcceleratorMetrics{AWS_TRAINIUM}` + `TrainiumMetrics`; `TrainiumHostMetrics` |
| `monitor/openmetrics.go` | `openmetrics.<endpoint>.<metric>.<index>`, labels and TYPE/UNIT/HELP dropped | `GenericMetric` |
| Legacy Python SDK only | `cpu.N.cpu_percent`, `ipu.*` | `CpuCoreMetrics` reserved; IPU not modeled |
