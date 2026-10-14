# Distributed Training Telemetry (Provenance v2)

Experimental. Each rank of a distributed training job writes pseudonymized rank, GPU, host, framework and platform telemetry as ordinary run files, without changes to the training script. The code lives in [`wandb/sdk/provenance/`](../../wandb/sdk/provenance) and [`core/internal/provenance/`](../../core/internal/provenance).

## The only user option

| Variable | Values | Effect |
| --- | --- | --- |
| `WANDB_X_PROVENANCE_LEVEL` | unset | Nothing. The startup hook does not import `wandb`. |
| | `0` | Baseline: phase timing, binding, host, GPU, network and platform counters. No extra collectives. |
| | `1` | Level 0 plus bounded NCCL flight-recorder reads, sampled gradient health, sampled GEMM diagnostics, one capped NCCL transport evidence read and one platform enrichment call. |

Any other string is ignored with one warning. The setting `x_provenance_level` mirrors the variable; it is not a separate feature flag. Every other `WANDB_X_PROVENANCE_*` variable below is launcher or test plumbing, not a user option.

### Early bootstrap requirement

Collection starts from `wandb_provenance_bootstrap.pth`, which the wheel build writes at the wheel root from [`startup.py`](../../wandb/sdk/provenance/startup.py). The `.pth` runs at interpreter startup, before the training script imports `torch`, so the variable must be in the environment of every rank process when it starts. Setting it later from Python does nothing. An editable install or a copied source tree without the `.pth` reports `startup_hook_missing` from `bootstrap.status()`.

A process becomes a writer only after its own successful `torch.distributed.init_process_group`. Helper processes such as data-loader workers import `wandb` (when the variable is set) but never create a run.

### Verify that unset does no work

```bash
env -u WANDB_X_PROVENANCE_LEVEL python -c 'import sys; assert "wandb" not in sys.modules'
WANDB_X_PROVENANCE_LEVEL=0 python -c 'import sys, wandb.sdk.provenance.bootstrap as b; assert b.status() == "armed" and "torch" not in sys.modules'
```

With the level unset, a run's config has no SDK feature 80 (`provenance_logs`), core never builds an emitter (`IsProvenance` in [`settings.go`](../../core/internal/settings/settings.go) checks only that a level is present), and the run has no `wandb-telemetry/` files.

### Version pinning

The POC supports TorchTitan at commit `6b3b7d4` only ([`framework/versions.py`](../../wandb/sdk/provenance/framework/versions.py)). Any other revision reports `torchtitan: unsupported/unsupported_integration` and installs no framework observers; GPU, host and platform collection still runs.

## Launch identity and launcher plumbing

Supported launchers: `torchrun` (`RANK`, `LOCAL_RANK`, `GROUP_RANK`, `WORLD_SIZE`), Slurm (`SLURM_PROCID`, `SLURM_LOCALID`, `SLURM_NODEID`, `SLURM_NTASKS`) and Open MPI (`OMPI_COMM_WORLD_*` plus `NODE_RANK`). See [`identity.py`](../../wandb/sdk/provenance/identity.py).

| Variable | Set by | Contract |
| --- | --- | --- |
| `WANDB_RUN_ID` | launcher | One value for the whole job, shared by every rank. Falls back to `TORCHELASTIC_RUN_ID` (ignored when it is torchrun's default `none`), `K8S_JOB_UID` or `SLURM_JOB_ID`. |
| `WANDB_PROJECT` | launcher | Required by every Forge Atlas launcher. Without it, a framework `wandb.init(project=...)` lands in the shared run with `run_conflict/project_mismatch`. |
| `WANDB_X_PROVENANCE_REDACTION_KEY` | launcher | Exactly 32 random bytes as 64 lowercase hex characters, generated once per job, shared by every rank through a Secret or a 0600 file. Never in argv, a ConfigMap, settings, protobufs or run files. |
| `WANDB_X_PROVENANCE_PROVIDER` | launcher | Only `coreweave` is accepted, as trusted evidence where DMI cannot identify the provider. Conflicting evidence selects the local adapter. |
| `WANDB_X_PROVENANCE_BUILD_BASE_COMMIT`, `WANDB_X_PROVENANCE_BUILD_SOURCE_DIFF_SHA256`, `WANDB_X_PROVENANCE_BUILD_WHEEL_SHA256`, `WANDB_X_PROVENANCE_BUILD_IMAGE_DIGEST` | launcher | Build identity copied from the build record into the manifest's `build` object: a 40-hex base commit, the 64-hex digest of every source change against it, the 64-hex wheel SHA-256, and the `sha256:<64 hex>` image digest. Invalid values are dropped and reported in `build_identity`. Not a user option. |
| `WANDB_X_PROVENANCE_SCENARIO`, `WANDB_X_PROVENANCE_TEST_PLUGINS` | tests | Load allowlisted fault-injection plugins. Never set in baseline jobs. |

The shared run is created in `shared` mode when the resolved mode is online, stays offline when offline, and is not created when disabled. Rank 0 is primary. Every writer reports its own exit as the run's final state, because the backend reopens a finished run on any later non-terminal request; the last writer to finish decides the state, and each manifest's `exit` keeps every rank's code. The shared run uses normal wandb init, finish and console settings, because a framework `wandb.init` on any rank can receive it. When a rank has no launcher run ID, or creating the shared run fails, it prints one local warning and collects nothing.

## Run files

All paths are under the run's files directory and upload through the normal run-files path ([`files.go`](../../core/internal/provenance/files.go)):

| Path | Writer | Refresh |
| --- | --- | --- |
| `wandb-telemetry/v2/primary.json` | rank 0 | Points at the current attempt's manifest and rollup. A write is skipped when the file already names a higher attempt, or the same attempt from another writer with a later `started_at`. |
| `wandb-telemetry/v2/manifest/<writer_id>.json` | every writer | 60 s and at drain. `started_at` (writer start, UTC wall clock, fixed for the writer), level, ranks, scheduler, framework revision, parallel coordinates, capabilities, quality, platform snapshot (Level 1 adds `transport` evidence), binding, device, `peak_flops`, `build`, `exit` (`code` and `reason`: `finish`; `attempt_failed` when the attempt's `init_process_group` failed; `terminated` on a signal to core; `parent_exited` when the training process died, for example a killed worker), `finalized`. |
| `wandb-telemetry/v2/rollup/<writer_id>.json` | every writer | 60 s and at drain. |
| `wandb-telemetry/v2/chunks/<slot>/<writer_id>-<seq>.jsonl.gz` | every writer | Sealed every 300 s, at 4 MiB raw, or at drain. `<slot>` is the UTC 20-minute bucket. |

Infrastructure records key bound-GPU samples as `gpu.<gpu_uuid_hmac>.<metric>`, never with the W&B `/l:<label>` suffix. Checkpoint records are written only for saves and loads that ran (TorchTitan returns `False` for a no-op). `primary.json` moves to a newer attempt as soon as that attempt's rank 0 writer writes its first manifest; an attempt whose rank 0 never starts a writer leaves the pointer at the last attempt that had one.

The manifest and rollup `quality` object carries `rejected_records`, `dropped_records`, `queue_depth`, `peak_memory_bytes`, `serialized_bytes`, `collector_cpu_ns`, `compression_ns`, `upload_registration_ns`, `gaps` and `backoff_transitions`. At Level 1, `collector_cpu_ns` also includes flight-recorder reads and the gradient and GEMM sampling on the step hook, and `peak_memory_bytes` also includes the GEMM probe tensors (24 MiB, held for the run) and each recorder dump while it is parsed.

`<writer_id>` is the core shared-mode client ID returned by the start handshake; `rank<N>` is only a label. Documents are replaced atomically on the same filesystem. Do not add `wandb-telemetry/v2/**` to `ignore_globs`.

## Peak-FLOP catalog

`core/internal/provenance/catalog.go` maps the bound device's NVML name to dense (no sparsity) Tensor Core peaks, and the manifest records the entry with its `catalog_version` (`nvidia-dense-2026-10`). `per_gpu` is the bf16 peak, which the frontend uses for MFU; `per_gpu_by_dtype` also carries fp8 where the device has it. Entries:

| NVML name | Device | bf16 dense | fp8 dense | Source |
| --- | --- | --- | --- | --- |
| `NVIDIA H100 80GB HBM3` | H100 SXM | 989.4 TFLOP/s | 1,978.9 TFLOP/s | [NVIDIA H100 datasheet](https://resources.nvidia.com/en-us-tensor-core/nvidia-tensor-core-gpu-datasheet) (sparsity figures halved) |
| `NVIDIA H200` | H200 SXM | 989.4 TFLOP/s | 1,978.9 TFLOP/s | [NVIDIA H200 datasheet](https://www.nvidia.com/en-us/data-center/h200/) (sparsity figures halved) |
| `NVIDIA A100-SXM4-80GB`, `NVIDIA A100-SXM4-40GB` | A100 SXM | 312 TFLOP/s | none | [NVIDIA A100 datasheet](https://www.nvidia.com/content/dam/en-zz/Solutions/Data-Center/a100/pdf/nvidia-a100-datasheet-us-nvidia-1758950-r4-web.pdf) |

The device name is known only when the bound GPU is joined, which needs the redaction key. Pricing is not copied: `pricing` always reports `unavailable/not_provided`, so cost views show GPU-hours without dollars.

## Redaction

With a valid key, every identifier (GPU UUID, hostname, instance ID, Pod and Node name, scheduler UID, PCI address, topology values) is replaced with `<kind>_` plus 24 lowercase hex characters from HMAC-SHA256, under policy `pseudonymous-1`. Python pseudonymizes binding identities before serialization; core validates that exact form and pseudonymizes raw XPU and cloud identities itself. With a missing or malformed key the joins are omitted, not hashed without a key, and `identity_join` reports the reason. PCI addresses are canonicalized to the sysfs form (`0000:3b:00.0`) before the HMAC, so NVML and sysfs addresses of one device get the same pseudonym. Metadata bodies and credential paths are never written.

## Flight recorder (Level 1)

Level 1 sets `TORCH_FR_BUFFER_SIZE=2000` before torch import only when neither `TORCH_FR_BUFFER_SIZE` nor `TORCH_NCCL_TRACE_BUFFER_SIZE` is set, and sets `TORCH_NCCL_ENABLE_TIMING=1` unless the user set it. The reader sizes the buffer the way torch does: `TORCH_FR_BUFFER_SIZE`, else `TORCH_NCCL_TRACE_BUFFER_SIZE`, else 2000 (TorchTitan sets 20000).

A daemon thread starts after the first step that finds `torch.distributed` initialized and reads at most once per 60 s, or less often while backed off (below). It picks the dump from the name of the default group's CUDA backend: `nccl` reads `_dump_nccl_trace`, which holds the CUDA-event recorder stock `ProcessGroupNCCL` writes to; any other name reads `_dump_fr_trace(backend=<name>)` (for example `nccl2` on current nightlies). Stack traces are never requested.

Completed entries are counted once per sequence number, per process group and separately for point-to-point ops, so coalesced ops count once and an entry that completes after a later one is still counted. Collectives are grouped by family (`all_reduce`, `all_gather`, `reduce_scatter`, `broadcast`, `all_to_all`, `send`, `recv`, `barrier`, `gather`, `scatter`, `reduce`, including `_into_tensor`, `_coalesced`, `_base` and `nccl:` variants); unknown names count as `other` and are never stored.

Every record from one read shares `read_id` (1, 2, ... per writer), `window_end_unix_ms` (the read's wall time, also the record time) and `window_start_unix_ms` (the previous read's end; absent on the first read). Each read emits one `flight_recorder` capability record, once a state is known, that carries `lost_count`: sequence numbers that left the ring before this read saw them, from ring wrap, from pending entries that never showed their completion, or past the 1024 pending entries tracked per group. Each family with new entries gets one `communication` record with `count`, `timed_count`, and `p50_ms`, `p99_ms`, `max_ms` and `total_ms` when any entry was timed. `bytes` (input sizes times dtype width) is present whenever every entry in the family has known sizes and dtypes, timed or not.

Each read dumps and parses the whole ring, so its cost follows how full the buffer is, not how long since the last read (an eager FSDP job fills 20000 entries in about 5 minutes). The CPU guard is 250 ms of reader-thread CPU per 60 s. A read that costs more is still published, and the next read waits 120 s if the read cost at most 500 ms, or 240 s if at most 1 s; a cheaper read returns to 60 s. So each read is followed by at least 60 s of wall time per 250 ms it cost, which holds the reader to about 0.42% of one core. A read over 1 s stops the reader, so it is the only read that can exceed 1 s. Entries that leave the ring during a longer wait are counted in the next read's `lost_count` as ring wrap.

Under CUDA graph replay (the TorchTitan default) collectives replayed from a graph never reach c10d, and the recorder hook skips them during capture, so the recorder only sees eager steps. Once a graph is captured, every read's capability is `partial/cuda_graph_replay` (after `backed_off`, before the recorder state), and its `communication` records cover eager collectives only.

## Collective schedule under CUDA graphs (Level 1, TorchTitan)

Around each `TrainingEngine.forward_backward` call in which a TorchTitan CUDA graph wrapper (`torchtitan.distributed.cuda_graph._manager._wrappers`) has no graph yet, Level 1 registers a c10d pre-hook (`ProcessGroup.register_pre_hook`) on every process group with a CUDA device and removes it when the call returns. If the first call registers no wrapper, graphs are off and the schedule never watches again. The hook does work only while `torch.cuda.is_current_stream_capturing()` is true: it records the op family (the flight recorder's table), the input bytes (`numel x element_size`) and the group. After capture, no hook is registered and the per-step cost is a few attribute reads. CPU-only groups are skipped because pre-hook maps are unlocked and checkpoint groups run on other threads. No `torch.distributed` function is wrapped, and no durations are recorded.

A call that captured a graph emits a `communication_schedule: available` capability with `schedule_id` and `effective_from_step`, and one `communication_schedule` record per family with:
- `schedule_id`: 1, 2, ... per writer;
- `effective_from_step`: the capture step, or the next step when warm-up calls ran eagerly in it;
- `collective`;
- `count_per_step` and `bytes_per_step`: captured counts and bytes times `replays_per_step`;
- `group_count`: the distinct groups that carried the family;
- `replays_per_step`: 1, or the accumulation group count with `cuda_graph_per_accumulation_group`;
- `source: cuda_graph_capture`.

A recapture (a wrapper whose graph was torn down) emits the next `schedule_id`, which replaces the previous one from its own step. Total replays are derived from the writer's `step` records, never from a guess. A failure removes the hooks and reports `communication_schedule: self_disabled/collector_failure`.

## Capability states

Each collector reports `available`, `partial`, `unavailable`, `permission_denied`, `timeout`, `unsupported` or `self_disabled`, with a reason. Missing data is never reported as healthy. Common reasons:

| Collector: status/reason | Meaning |
| --- | --- |
| `identity_join: partial/missing_redaction_key` | No key in the environment; sensitive joins omitted. |
| `identity_join: partial/invalid_redaction_key` | Key present but not 64 lowercase hex characters. |
| `writer: partial/run_conflict` | The script called `wandb.init` with another run ID. The shared writer keeps running and the user's run becomes `wandb.run` beside it. |
| `writer: partial/run_conflict/project_mismatch` | `wandb.init` used the shared run ID with another project. The shared run is returned with one warning. |
| `nccl_transport: partial/configured_and_loaded`, `configured_only`, `loaded_only`, `configured_not_loaded` | Level 1 evidence from one capped (4 MiB) read of `/proc/self/maps` for the loaded NCCL net plugin, a check that `/sys/class/infiniband` is non-empty (names are not kept), and allowlisted NCCL network variables, after the first step. TCPX, TCPXO and EFA come only from their plugin libraries; `ib` needs an RDMA device or an IB plugin, because `libibverbs` loads on every host; otherwise `socket`. `platform.transport.name` is `socket`, `ib`, `tcpx`, `tcpxo` or `efa`; it is configured and loaded evidence, never the negotiated transport. Only families and numeric values are kept; paths and interface names are reduced to `set`. NCCL logs are never enabled or read. |
| `nccl_transport: unavailable/no_evidence`, `unrecognized_plugin`, `maps_truncated` | No NCCL library or configuration was seen, an unknown plugin was loaded without configuration, or the maps read hit its cap. |
| `flight_recorder: available` | The last read that found new collectives found timed ones and emitted `communication` records. A read with nothing new keeps the previous state. |
| `flight_recorder: partial/recorder_detached`, `recorder_empty`, `no_completed_collectives` | The dump had no entries and no registered process group (the backend feeds a recorder this read cannot see), had registered groups but no entries, or had entries none of which ever completed. |
| `flight_recorder: partial/no_recognized_collectives`, `no_timing` | Every new completed entry was `other` (`count` holds how many), or no new entry had a duration. |
| `flight_recorder: partial/cuda_graph_replay` | A CUDA graph was captured, so replayed collectives bypass the recorder; its records cover eager steps only, and `communication_schedule` carries per-step counts and bytes. |
| `flight_recorder: partial/backed_off` | The read cost more than 250 ms of thread CPU, so the next read is later than 60 s; `interval_s` holds the wait (120 or 240). The read's collectives are still emitted. It returns to the recorder state once a read costs 250 ms or less. |
| `flight_recorder: partial/buffer_too_large`, `self_disabled/cpu_budget` | The buffer is over 20000 entries (the size is in `count`) and is never read, or one read used more than 1 s of thread CPU (the milliseconds are in `count`). Both stop the reader. |
| `flight_recorder: unavailable/recorder_unavailable` | No initialized default process group, a buffer size of 0 or a non-integer, no dump function for the backend, a dump over 32 MiB or 20000 entries, more than 1024 tracked process groups (point-to-point counted separately), or a read that raised. |
| `gradient_health: available`, records `partial/tensor_sample` | Every 100 steps, fused on-device L2 norms over a fixed stride of at most 64 local gradient tensors, copied back without a host sync and read on a later step. `finite_count`, `nonfinite_count` and `count` are tensors; `norm` covers the sampled tensors. |
| `gradient_health: self_disabled/cpu_budget` or `collector_failure` | A sample after the first used more than 20 ms of thread CPU, or the scan raised. GEMM probes continue. |
| `active_diagnostics: self_disabled/gpu_budget` or `collector_failure` | A timed 2048x2048 fp16 GEMM, after one untimed warm-up call, took over 100 ms between its CUDA events, or raised. Gradient health continues. `queue_pressure` disables both. |
| `gpu_metrics: unavailable/environment_not_probed`, `no_nvidia_gpu`, `<identity_join reason>`, `binding_not_proven`, `binding_not_joined` | GPU samples cannot be joined to the bound device; each dropped sample window also counts as a `quality.gaps`. |
| `driver_counters: partial/no_known_counters` | `ethtool -S` ran but no allowlisted counter name matched. |
| `nccl_sweep: unsupported/unsupported_boundary` | No proven all-rank boundary at the pinned framework, so no active sweep runs. |
| `gradient_health`, `active_diagnostics: unavailable/cuda_unavailable` | CUDA was not initialized, so Level 1 diagnostics did not run. |
| `... unavailable/step_threshold_not_reached` | The run ended before any step reached the sampling gate. |
| `mission_control: unavailable/missing_credentials` | CoreWeave Mission Control has no scoped credential contract; no call is made. AWS and OCI Level 1 enrichment use the same reason when no SDK credential exists. |
| `kubernetes: unavailable/credentials_missing` | No readable in-cluster service account token or CA for the current Pod/Node read (`pod_identity_missing` when `K8S_POD_NAME`/`K8S_NAMESPACE` are unset). |
| `peak_flops: unavailable/device_unknown` or `device_not_in_catalog` | No bound device name, or the device has no catalog entry; MFU is unavailable. |
| `build_identity: unavailable/not_provided` | The launcher injected no build identity. `partial/incomplete_build_identity` means some fields are missing; `invalid_build_identity` means some values were malformed and dropped. |
| `pricing: unavailable/not_provided` | No allowlisted rate is copied into the manifest. |
| `provider: partial/provider_conflict` | More than one provider matched; the local adapter is used. |
| `*: permission_denied`, `timeout`, `request_failed` | Bounded metadata or API reads failed; stable identity is retried on collects 2, 4, 8 and so on. |

## Attempts and termination

- When `init_process_group` raises, the rank still creates its writer and records a `lifecycle` record (`event: init_process_group`, `reason: attempt_failed`, `max_restarts` when torchelastic sets it), so an attempt that never initializes is visible. This waits up to the 5 s init timeout before the original exception propagates.
- `attempt` comes from `TORCHELASTIC_RESTART_COUNT` or `SLURM_RESTART_COUNT` and is per node under torchelastic: each agent counts only its own worker-group failures, and an agent that restarts healthy workers to re-rendezvous after another node failed does not increment it (`torch/distributed/elastic/agent/server/api.py` `_invoke_run`, "membership changes do not count as retries"). After a single-node failure the failing node's ranks report attempt 1 while the other nodes' new writers report attempt 0 again. Do not compare `attempt` across nodes; order a rank's writers by the manifest `started_at` instead (writers from older SDKs without it order by their first record).
- A manual or Job-level relaunch with the same `WANDB_RUN_ID`, or an in-place container restart, starts at attempt 0 again. The frontend still separates it: a rank's writer takes its own `attempt` or one more than the rank's previous writer, whichever is higher, so attempts never merge and consistent raw counts (including gaps) are kept.
- SIGTERM or SIGINT reaching `wandb-core` records exit code 128 plus the signal (143 for SIGTERM) through a bounded 5 s synthetic exit, then core stops as before. Parent-process exit records exit code 1.
- SIGTERM sent only to `torchrun` is forwarded to the workers but not to their `wandb-core`, so core takes the parent-exit path and records exit 1, not 143. Signal every process in the job to record 143.
- A killed worker leaves its writer's last sealed state; a killed `wandb-core` leaves an unfinalized manifest, which the frontend shows as an incomplete tail once the run is terminal.

## Tests

```bash
.venv/bin/python -m pytest -q tests/unit_tests/test_provenance_*.py
.venv/bin/python -m pytest -q tests/system_tests/test_core/test_provenance_bootstrap.py tests/system_tests/test_core/test_provenance_termination.py
(cd core && go test -race -count=1 ./internal/provenance/...)
```

The system tests need the in-checkout `wandb/bin/wandb-core` and a local test server (`tools/local_wandb_server.py`).
