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
| `wandb-telemetry/v2/manifest/<writer_id>.json` | every writer | 60 s and at drain. Level, ranks, scheduler, framework revision, parallel coordinates, capabilities, quality, platform snapshot (Level 1 adds `transport` evidence), binding, device, `peak_flops`, `build`, `exit` (`code` and `reason`: `finish`; `attempt_failed` when the attempt's `init_process_group` failed; `terminated` on a signal to core; `parent_exited` when the training process died, for example a killed worker), `finalized`. |
| `wandb-telemetry/v2/rollup/<writer_id>.json` | every writer | 60 s and at drain. |
| `wandb-telemetry/v2/chunks/<slot>/<writer_id>-<seq>.jsonl.gz` | every writer | Sealed every 300 s, at 4 MiB raw, or at drain. `<slot>` is the UTC 20-minute bucket. |

Infrastructure records key bound-GPU samples as `gpu.<gpu_uuid_hmac>.<metric>`, never with the W&B `/l:<label>` suffix. Checkpoint records are written only for saves and loads that ran (TorchTitan returns `False` for a no-op). `primary.json` moves to a newer attempt as soon as that attempt's rank 0 writer writes its first manifest; an attempt whose rank 0 never starts a writer leaves the pointer at the last attempt that had one.

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

With a valid key, every identifier (GPU UUID, hostname, instance ID, Pod and Node name, scheduler UID, PCI address, topology values) is replaced with `<kind>_` plus 24 lowercase hex characters from HMAC-SHA256, under policy `pseudonymous-1`. Python pseudonymizes binding identities before serialization; core validates that exact form and pseudonymizes raw XPU and cloud identities itself. With a missing or malformed key the joins are omitted, not hashed without a key, and `identity_join` reports the reason. Metadata bodies and credential paths are never written.

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
| `flight_recorder: unavailable/recorder_unavailable` | Level 1 could not read the NCCL flight recorder (no process group, no recorder in this PyTorch build, or buffer unset). Reads use `_dump_nccl_trace`, which holds the CUDA recorder NCCL writes to; `_dump_fr_trace(backend="nccl")` reads a separate CPU-event recorder and is used only when `_dump_nccl_trace` is absent. Level 1 sets `TORCH_NCCL_TRACE_BUFFER_SIZE=2000` and `TORCH_NCCL_ENABLE_TIMING=1` before torch import unless the user set them. Collectives are grouped by family (`all_reduce`, `all_gather`, `reduce_scatter`, `broadcast`, `all_to_all`, `send`, `recv`, `barrier`, `gather`, `scatter`, `reduce`, including `_into_tensor`, `_coalesced`, `_base` and `nccl:` variants); unknown names count as `other` and are never stored. `available` only once `communication` records are emitted; `partial/no_timing` when entries have no durations; `partial/recorder_empty` when a read returns no entries; `partial/no_recognized_collectives` (with `count`) when every new entry is `other`; `partial/generic_recorder` when only `_dump_fr_trace` exists. The buffer in effect (`TORCH_FR_BUFFER_SIZE`, else `TORCH_NCCL_TRACE_BUFFER_SIZE`; TorchTitan sets 20000) is read at most once per 60 s, up to 20000 entries and 32 MiB per dump; larger buffers report `partial/buffer_too_large` with the size in `count` and are never read, and a read over 250 ms of thread CPU reports `self_disabled/cpu_budget`. |
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
- The attempt comes from `TORCHELASTIC_RESTART_COUNT` or `SLURM_RESTART_COUNT`. A manual or Job-level relaunch with the same `WANDB_RUN_ID` starts at attempt 0 again; the frontend splits it into a new launch when a writer repeats a (rank, restart count) already held by another writer of the current launch, which also covers in-place container restarts, or when it starts after every earlier writer finalized or went silent for 60 s. It shifts the attempt so attempts never merge.
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
