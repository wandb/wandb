# Test Coverage Analysis & Improvement Proposals

_Analysis date: 2026-06-20_

This document analyzes the current state of automated test coverage across the
`wandb/wandb` codebase (Python SDK + Go `core`) and proposes prioritized areas
for improvement. The findings are based on a structural analysis of the source
tree against the test tree, not a line-by-line coverage run, so percentages
below describe **breadth of coverage** (which modules are exercised at all)
rather than precise line coverage.

## How the codebase is organized

- **Python SDK** (`wandb/`): ~364 non-generated, non-vendored modules,
  ~100k LOC.
- **Go core** (`core/`): 463 source files, 156 `_test.go` files.
- **Tests** (`tests/`):
  - `tests/unit_tests/` — 146 test files
  - `tests/system_tests/` — 106 test files (including `test_functional/` for
    framework integrations)

Coverage is reported to Codecov with per-area flags (`sdk`, `sdk-internal`,
`sdk-launch`, `sdk-service`, `apis`, `core`, `other`) — see `.codecov.yml`.

## Top-line findings

- **~32k of ~101k non-generated Python source LOC (≈32%) are not referenced by
  any test** (no test imports/exercises the module by its dotted path). This is
  a breadth measure; core modules exercised functionally (e.g. via
  `wandb.init()`) are counted as covered.
- **Framework integrations are the single largest gap.** Of 23 integration
  packages, roughly **11 have no automated tests at all** (unit or functional).
- **`wandb/sdk/lib/` (utility layer, ~9k LOC) is ~59% unreferenced** — much of
  it is pure, easily unit-testable logic.
- **Several Go `core` packages with non-trivial logic have zero tests**, most
  notably `internal/settings` (~680 LOC).

---

## Prioritized improvement areas

### P0 — Framework integrations (largest, highest-churn gap)

Integration packages with **no test references** (neither unit nor
`system_tests/test_functional`):

| Integration | Status |
|---|---|
| `diffusers` (1,113 LOC) | no tests |
| `ultralytics` (1,139 LOC) | no tests |
| `openai` (482 LOC) | no tests |
| `huggingface` (234 LOC) | no tests |
| `prodigy` (284 LOC) | no tests |
| `sacred`, `fastai`, `gym`, `lightgbm`, `tensorboard`, `sb3` | little/no tests |
| `sklearn` (1,715 LOC, 16 files) | only 1 incidental reference |
| `torch` (556 LOC), `tensorflow` (54 LOC) | thin coverage |

These are user-facing callbacks/loggers that break silently when upstream
frameworks change their APIs. They are also where most user-reported bugs land.

**Proposal:**
- Establish a consistent pattern under `tests/system_tests/test_functional/<framework>`
  for every shipped integration (several already exist: keras, lightning,
  xgboost, catboost, dspy, metaflow, jax). Backfill the missing ones, starting
  with the largest/most-used: `diffusers`, `ultralytics`, `openai`, `sklearn`.
- For resolver-heavy integrations (`diffusers/resolvers/multimodal.py`,
  `openai/fine_tuning.py`), add **unit tests with mocked framework objects** to
  cover the data-transformation logic without requiring the heavy dependency.

### P1 — `wandb/sdk/lib/` utility layer (~59% unreferenced, ~5.4k LOC)

This layer is mostly pure helpers and is the cheapest place to add high-value
unit tests. Notable untested modules:

- `redirect.py` (874 LOC) and `console_capture.py` (308 LOC) — stdout/stderr
  interception. **High risk**: bug-prone, platform-dependent, patches global
  state at import time (per its own docstring it conflicts with pytest capture),
  and regressions here corrupt every user's logs.
- `asyncio_compat.py` (291) / `asyncio_manager.py` (256) — concurrency
  primitives; subtle bugs are hard to catch in integration tests.
- `progress.py` (359), `import_hooks.py` (276),
  `service/service_connection.py` (377) — service connection logic.

**Proposal:** Add focused unit tests for the pure helpers first
(`asyncio_compat`, `import_hooks`, `progress` rendering). For
`redirect`/`console_capture`, add subprocess-based tests that assert captured
output round-trips correctly across platforms.

### P2 — `wandb/sdk/data_types/` (~45% unreferenced, ~4k LOC)

Media/data type serialization is user-facing and version-sensitive (artifact
format compatibility). Untested or thinly-tested modules include:

- `object_3d.py` (539), `saved_model.py` (439), `graph.py` (439),
  `video.py` (304), `molecule.py` (253), `helper_types/bounding_boxes_2d.py`,
  `helper_types/image_mask.py`.

**Proposal:** Add serialization/round-trip unit tests (construct → `to_json` →
reload → assert structure) for each media type, plus validation-error cases for
malformed inputs. These run fast and guard the on-disk/artifact format.

### P3 — Go `core` packages with no tests

Excluding generated code and `*test` helper packages, the meaningful untested
Go packages are:

| Package | LOC | Notes |
|---|---|---|
| `internal/settings` | ~680 | Core settings logic, derived from proto — **highest priority** |
| `pkg/server/listeners` | ~268 | Socket/TCP listener setup |
| `internal/corelib` | ~85 | |
| `internal/runenvironment` | ~71 | |
| `internal/pfxout` | ~56 | Prefixed output writer |
| `internal/timer` | ~51 | |

**Proposal:** Prioritize `internal/settings` — it has substantial logic and is a
dependency of nearly every other package, so bugs propagate widely. Add table
tests for `pkg/server/listeners` (port selection, error paths).

### P4 — Misc. high-value Python modules

Large modules not referenced by dotted path (note: some are exercised
functionally and may already have effective coverage — verify with a real
coverage run before investing):

- `wandb/wandb_controller.py` (714) — sweep controller.
- `wandb/sdk/internal/tb_watcher.py` (520), `handler.py` (842).
- `wandb/cli/` — `beta_sync.py` (340), `leet.py` (328), `beta_sandbox.py` (301)
  largely untested; CLI surface is user-facing.
- `wandb/automations/_filters/` operators/run_metrics — filter-expression logic
  that benefits from unit tests.

---

## Recommended next steps

1. **Run an actual coverage report** (`pytest --cov` / `go test -cover`) to
   convert these breadth findings into precise line-coverage numbers and
   confirm which "unreferenced" modules are in fact covered functionally.
2. **Adopt a per-integration functional-test convention** and backfill the ~11
   integrations that have none (start P0 list).
3. **Add a unit-test sweep for `wandb/sdk/lib/`**, prioritizing the
   console-capture/redirect risk area.
4. **Backfill `core/internal/settings` Go tests** as the highest-value core gap.
5. Consider a Codecov **patch target** (currently `target: 0`) for new code so
   coverage doesn't regress further on the under-tested areas above.

> Methodology note: "unreferenced" means no test file references the module by
> its full dotted import path. This under-counts coverage for modules exercised
> indirectly through end-to-end flows (e.g. `wandb_init.py`, `wandb_run.py`) and
> should be validated against a real coverage run before committing engineering
> time.
