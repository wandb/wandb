# SDK Development Guide

This page is the practical companion to [CONTRIBUTING.md](../../CONTRIBUTING.md). Use `CONTRIBUTING.md` as the source of truth for exact commands; use this page to choose the right workflow for SDK architecture work.

## Local environment

The SDK spans Python, Go, and Rust:

- Python: public SDK and API, user process behavior, integrations, tests.
- Go: `wandb-core`, sync, filestream, file transfer, run processing, Public API routing.
- Rust: accelerator monitoring (`wandb-xpu`) and parquet support.

Recommended baseline from `CONTRIBUTING.md`:

```shell
uv python install 3.13
uv venv
source .venv/bin/activate
uv pip install nox
uv pip install --reinstall --refresh-package wandb -e .
```

If you modify Go or Rust code, reinstall the editable package so the bundled binaries rebuild.

## Choosing a test layer

Start with the layer where the guarantee lives.

| Change type | First test to consider | Notes |
| --- | --- | --- |
| Pure Python validation or API ergonomics | `tests/unit_tests/...` | Keep core out if behavior is Python-only. |
| Run lifecycle behavior visible to users | `tests/system_tests/test_functional/...` | Prefer a small script-style system test. |
| Core record handling | Go tests near `core/internal/stream` or target package | Test handler/sender behavior directly where possible. |
| Filestream batching/retry behavior | `core/internal/filestream` tests | Avoid full SDK tests for pure batching logic. |
| File uploads | `core/internal/runfiles` or `core/internal/filetransfer` tests | Use test helpers; avoid real storage when possible. |
| Public API routing through core | Python API tests plus `core/internal/wbapi` tests | Cover exception surface in Python. |
| Proto schema changes | Proto generation plus Python/Go compile tests | Update generated code in all language targets. |
| System metrics | `tests/system_tests/test_system_metrics`, `xpu/src`, and `core/internal/monitor` | Hardware-dependent tests need care. |

## Common commands

Python tests:

```shell
pytest -s -vv tests/path/to/test_file.py
```

Start a local W&B test server (`local-testcontainer`) for system tests:

```shell
python tools/local_wandb_server.py start
```

Go tests:

```shell
cd core
go test ./internal/stream ./pkg/server
```

Rust tests:

```shell
cd xpu
cargo test --verbose
```

All Go tests. The repo's pre-commit hook (`core/scripts/pre-commit-hooks/run-go-unit-tests.sh`) runs the short suite; add `-race` for a thorough local pass:

```shell
cd core
go test -short -timeout 30s ./...   # what the pre-commit hook runs
go test -count=1 -race ./...        # thorough, slower
```

Proto generation:

```shell
nox -t proto
```

Pre-commit hooks:

```shell
uv tool install prek
prek install
prek run ruff-format --all-files --hook-stage pre-push
```

## Proto changes

The protobuf files in [`wandb/proto`](../../wandb/proto) generate Python stubs under `wandb/proto` and Go stubs under `core/pkg/service_go_proto`.

When changing a proto:

1. Change the `.proto` file.
2. Run `nox -t proto`.
3. Update all Python and Go call sites.
4. Add tests at the producer and consumer boundary.
5. Re-check backward compatibility. Existing offline transaction logs and older SDK/core combinations may matter.

## Code ownership by behavior

Use this as the first "where do I look?" table:

| Behavior | Start here | Then inspect |
| --- | --- | --- |
| `wandb.init()` hangs | `wandb/sdk/wandb_init.py` | service startup, core `handleInformInit`, `runupserter` |
| `run.log()` drops or mis-steps data | `wandb/sdk/wandb_run.py` | `Interface.publish_partial_history`, core handler partial history |
| Summary wrong | `core/internal/runsummary` | sender `sendSummary`, handler summary response |
| Finish hangs | `Run._on_finish` | sender `finishRunSync`, operation stats, filestream/filetransfer |
| File missing | `Run.save` | `runfiles.Uploader`, file transfer task, filestream uploaded files update |
| Artifact issue | `Run.log_artifact` or `Run.use_artifact` | `core/pkg/artifacts`, sender artifact cases |
| Offline sync issue | `wandb/cli/beta_sync.py` | `ServiceConnection.init_sync`, `core/internal/runsync` |
| Public API error changed | `wandb/apis/public/service_api.py` | `ServiceConnection.api_request`, `core/internal/wbapi` |
| Core service lifetime | `service_connection.py` | `service_process.py`, `core/pkg/server` |
| System metric issue | `core/internal/monitor` | `xpu`, `SystemMonitor`, `XPUResourceManager` |

## Review habits

Good SDK changes preserve a few invariants:

- User APIs remain synchronous only where users already expect synchronization.
- `run.log()` and console capture stay lightweight in the user process.
- Any operation that waits on core uses a mailbox handle and has a clear timeout story.
- Finish order is deliberate; do not reorder shutdown stages casually.
- Offline and online behavior are both considered.
- Multiprocessing and shared-core cases are considered when touching service tokens, attach, or socket behavior.
- Generated protobuf files are updated together.
- Tests avoid requiring private backend access unless the behavior is truly system-level.

## External contributors

External contributors may not be able to run system tests that require private infrastructure or backend credentials. Keep unit tests useful and isolate private-system-test-only coverage to the smallest possible surface.

## When to update these docs

Update this doc set when you:

- Move a public user flow to a different core path.
- Change the IPC protocol or service lifetime model.
- Change history, summary, files, artifacts, sync, or system metrics ownership.
- Remove or substantially rewrite a package listed in [Source Map](source-map.md).
- Find a stale statement while onboarding someone. Fix it immediately; stale architecture docs compound quickly.
