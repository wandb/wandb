# Provenance fixtures (not yet generated)

The synthesized corpus one level up (`../`) encodes only *this repo's
belief* about what old and pre-Go-core `.wandb` files look like. This
directory is meant to hold **2 real files, generated once by hand from
actual PyPI releases**, to check that belief against reality:

1. **A recent release** (pre-PR #12110) — validates the belief that an old
   auto-step history row carries the step three ways: `record.Step` (a
   `HistoryStep` message), an item keyed by `NestedKey: ["_step"]`, and a
   matching `SummaryRecord._step`. This is what `old_auto_steps` in the
   synthesized corpus assumes.
2. **A pre-Go-core Python-sender release** — validates the belief that the
   older, pure-Python sender wrote `_step` as a **flat** `Key`, not a
   nested one. This is what `old_auto_steps_flat_keys` assumes, and is the
   shape the PR's own tests never exercise.

These are intentionally **not** committed yet — generating them means
installing arbitrary old `wandb` releases and running real offline logging
sessions, which is a manual, one-off task rather than something to automate
in CI. What follows is the recipe to do it.

## Why these can be generated fully offline

`wandb.init(mode="offline")` writes the `.wandb` transaction log locally
without ever contacting a backend, so no server, API key, or network
access (beyond PyPI) is needed to produce either fixture.

## Recipe

Do this somewhere outside the repo (e.g. `/tmp/wandb-provenance`) so the
throwaway venvs and run directories don't pollute your working tree.

### 1. Pick versions

- **Recent release**: any released version before PR #12110 merges works,
  since the PR hasn't landed in a release yet. As of this writing the
  latest is what's in this repo's `CHANGELOG.md` (`## [0.28.1]`). Use that,
  or `pip index versions wandb` to see what's newest when you actually run
  this.
- **Pre-Go-core release**: needs a version where the *pure-Python* sender
  was the default backend, not just where `wandb-core`/`nexus` was
  available as an opt-in (`wandb.require("core")` existed as an
  experimental opt-in well before it became the default in `0.18.0`,
  2024-09-11 — see `CHANGELOG.md`). `0.16.6` (2024-04) is a safe pick: old
  enough that the legacy Python sender is what actually runs by default.
  If you want to double check a candidate version before committing to it,
  install it and print `wandb.__version__` plus inspect
  `wandb/sdk/internal/sender.py` in the installed package — the
  pre-Go-core sender is the one that builds `HistoryRecord`s directly in
  Python (search for `_step` handling in that file).

### 2. Generate each fixture in its own throwaway venv

```bash
WORKDIR=/tmp/wandb-provenance
mkdir -p "$WORKDIR"

# --- Recent release (nested-key + record.Step + summary._step) ---
python3 -m venv "$WORKDIR/venv-recent"
"$WORKDIR/venv-recent/bin/pip" install --upgrade pip
"$WORKDIR/venv-recent/bin/pip" install "wandb==0.28.1"   # adjust if needed

cat > "$WORKDIR/gen_recent.py" <<'EOF'
import os
os.environ["WANDB_MODE"] = "offline"
os.environ["WANDB_ERROR_REPORTING"] = "false"

import wandb

run = wandb.init(project="compat-corpus-provenance")
for i in range(3):
    run.log({"x": i})
run.finish()
print("RUN_DIR:", run.settings.sync_dir)
EOF

(cd "$WORKDIR" && venv-recent/bin/python gen_recent.py)

# --- Pre-Go-core release (flat-key _step) ---
python3 -m venv "$WORKDIR/venv-pre-core"
"$WORKDIR/venv-pre-core/bin/pip" install --upgrade pip
"$WORKDIR/venv-pre-core/bin/pip" install "wandb==0.16.6"   # adjust if needed

# Same script works unchanged against the old API.
(cd "$WORKDIR" && venv-pre-core/bin/python gen_recent.py)
```

Each run prints its `RUN_DIR`, e.g.
`/tmp/wandb-provenance/wandb/offline-run-20260807_120000-ab12cd34`. Inside
it is `run-ab12cd34.wandb` — that's the file you want.

### 3. Verify the shape before committing

Sanity-check each `.wandb` file actually has the shape you expect, using
this repo's own reader so you're checking with the same code the tests
use:

```bash
cd core && go run ./cmd/... # or write a 5-line throwaway main.go using
# transactionlog.OpenReader + observability.NewNoOpLogger to dump records,
# or temporarily point GoldenLogRecords-style logic at the file.
```

The quickest check is usually just `strings run-*.wandb | grep -c _step`
combined with eyeballing whether `_step` shows up once or twice per history
row (once = flat/nested key only; twice = key *and* a duplicate — not
expected either way, so investigate if you see it).

### 4. Commit

Copy (don't move — keep your throwaway venvs disposable) each file into:

```
tests/assets/compat_logs/provenance/offline-run-recent-release/run-recent-release.wandb
tests/assets/compat_logs/provenance/offline-run-pre-core-release/run-pre-core-release.wandb
```

These two are **excluded** from `TestGoldenLogs_UpToDate` (that test only
checks the synthesized corpus) but **are** counted against the 16 KiB
provenance budget in `TestGoldenLogs_SizeBudget`
(`core/internal/transactionlogtest/golden_test.go`) — real runs are much
larger than synthesized ones (they embed timestamps, host info, telemetry,
system metrics), so if a fixture is too big, strip the script down to the
minimum (`project=`, 3 `log()` calls, `finish()`) rather than trimming the
file after the fact.

### 5. Add the bridge test

Once both files are committed, add
`TestProvenanceFixturesMatchSynthesizedShape` next to
`TestGoldenLogs_UpToDate` in
`core/internal/transactionlogtest/golden_test.go`. It should read each
provenance file's first history row and compare *which* step fields are
set and in which key style — never the values, which aren't reproducible —
against `old_auto_steps` (for the recent-release file) and
`old_auto_steps_flat_keys` (for the pre-core-release file). That
comparison is what turns "we believe this is the old shape" into "we
checked it against a real file," and — because it compares shape, not
exact bytes — it can't be silenced by regenerating the fixture the way a
byte-equality check could.

## Never regenerate to make a test pass

Unlike the synthesized corpus, these two files should be generated
**once** and then left alone. If a test built on them starts failing,
that's a real signal — either the code broke real-file compatibility, or
the belief encoded in the synthesized corpus was wrong and needs fixing
there, not here.
