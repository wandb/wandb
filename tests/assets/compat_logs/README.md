# Transaction log compatibility fixtures

This directory keeps `.wandb` fixtures that protect transaction-log compatibility across old and new run shapes.

## Layout

```text
tests/assets/compat_logs/
  README.md
  synthesized/offline-run-<case>/run-<case>.wandb
  captured/offline-run-<name>/...
```

- `synthesized/` contains generated fixtures from `goldenCorpus` in `core/internal/transactionlogtest/golden_test.go`.
- `captured/` is for real fixtures captured from specific released `wandb` versions.

## Synthesized fixtures (source of truth)

- Do not hand-edit files under `synthesized/`.
- Edit `goldenCorpus`, then regenerate:

```bash
cd core && go test ./internal/transactionlogtest -update-golden-logs
```

- `TestGoldenLogs_UpToDate` checks committed `synthesized/` bytes match generated output.
- Review every diff under `tests/assets/compat_logs/synthesized/` before commit.

Binary review workflow:

```bash
# See which fixtures changed.
git diff --name-only -- tests/assets/compat_logs/synthesized

# Inspect old/new record-level content for one changed file.
uv run tools/inspect_tool.py tests/assets/compat_logs/synthesized/offline-run-<name>/run-<name>.wandb
git show HEAD:tests/assets/compat_logs/synthesized/offline-run-<name>/run-<name>.wandb > /tmp/old.wandb
uv run tools/inspect_tool.py /tmp/old.wandb
```

Optional: add a `.gitattributes` diff driver for `*.wandb` that shells out to `uv run tools/inspect_tool.py`, so `git diff` shows decoded records instead of binary blobs.

## Captured fixtures (real release snapshots)

- Use captured fixtures to validate assumptions against real `.wandb` files from released SDK versions.
- Captured fixtures are excluded from `TestGoldenLogs_UpToDate`.
- Treat captured fixtures as snapshots: do not regenerate them to silence a failure.

Generate one captured fixture:

```bash
python tools/capture_compat_log.py --wandb-version 0.28.1
python tools/capture_compat_log.py --wandb-version 0.16.6 --label pre-core
```

Script outputs to `captured/offline-run-<fixture-name>/`:

- `run-<fixture-name>.wandb`
- `generate-<fixture-name>.py` (exact Python used)
- `metadata-<fixture-name>.json` (inputs and environment details)

The script refuses to overwrite existing files unless `--force` is provided.
With `--force`, it prints a warning before replacing files.
