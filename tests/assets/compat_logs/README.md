# Transaction-log compatibility corpus

This directory pins the on-disk shape of `.wandb` transaction logs across the
format change made by wandb PR #12110 (`feat(sdk): allow resume for offline
runs`, merge base `4f92599d0`). It exists so that a change to how history
steps are read or written gets caught by a byte-level test instead of by a
user's old runs failing to sync.

## Layout

```
offline-run-<case>/run-<case>.wandb   # one directory per synthesized fixture
provenance/                            # 2 real, hand-generated files
```

Each `offline-run-<case>` directory name matches the precedent set by the
repo's original fixture,
`tests/assets/wandb/offline-run-20210216_154407-g9dvvkua/`: `wandb sync`'s
online/offline heuristic keys on the `offline-run-` prefix only, and
`copy_asset(...)` in `tests/conftest.py` works on this shape unchanged. The
run ID in each fixture's records equals the case name, so both Go and Python
tests can refer to it directly, e.g. `snapshot.history(run_id="old_auto_steps")`.

## Source of truth

The synthesized fixtures (everything except `provenance/`) are **generated,
not hand-edited**. The source of truth is the `goldenCorpus` table in
[`core/internal/transactionlogtest/golden_test.go`](../../../core/internal/transactionlogtest/golden_test.go).
`TestGoldenLogs_UpToDate` in that file asserts the committed bytes here match
what `goldenCorpus` produces — the main failure mode of a compatibility
corpus is a future change quietly regenerating a fixture to make a failing
test pass, and this makes that show up as a reviewable diff instead.

To change a fixture:

1. Edit the matching entry in `goldenCorpus`.
2. Regenerate:

   ```bash
   cd core && go test ./internal/transactionlogtest -update-golden-logs
   ```

3. Review the diff under `tests/assets/compat_logs/` — that diff **is** the
   change to what this repo claims a `.wandb` file looked like. If you can't
   explain why the bytes changed, don't commit it.

Do not hand-edit the `.wandb` files here; `TestGoldenLogs_UpToDate` will
immediately flag the drift.

## Why synthesized fixtures at all

A real run's `.wandb` file embeds `start_time`, host, Python version,
telemetry, and system metrics, none of which are deterministic and none of
which matter for step-compatibility testing. A synthesized corpus is
byte-reproducible (`TestGoldenLogs_UpToDate` proves it in CI), an order of
magnitude smaller, and every field in it is there because a test needs it.

Deliberate simplifications (not drift): history rows omit `_runtime` and
other system keys; summary records carry only `_step` (or a single metric
for `old_no_history`), not the full logged-metric snapshot a real run would
have. Real flushes also write the Summary record before its History record;
the synthesized fixtures match that order. Header version byte 0 pins the
pre-PR history encoding (`old_*` cases); version 1 pins the post-PR encoding
(`new_*` cases). Current readers accept both; older wandb releases reject
version 1 files and should sync them with an upgraded `wandb beta sync`.
Shared-mode runs persist `shared_mode: true` on the transaction log's
`RunRecord`; `wandb beta sync` reads it so shared history uploads omit the
step axis.

The tradeoff is that it only encodes *this repo's belief* about what an old
or pre-Go-core `.wandb` file actually looks like. `provenance/` exists to
check that belief against reality; see
[`provenance/README.md`](provenance/README.md).

## Size budget

`TestGoldenLogs_SizeBudget` enforces: synthesized ≤ 4 KiB, provenance ≤ 16
KiB, total ≤ 64 KiB. This is the only thing stopping the corpus from
becoming a dumping ground — keep new fixtures minimal.
