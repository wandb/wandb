# Vendoring notes

This directory contains vendored code from the [watchdog](https://github.com/gorakhargosh/watchdog) project.
It is based on the [v0.9.0](https://github.com/gorakhargosh/watchdog/releases/tag/v0.9.0) release and contains
the following changes:

- Removed dependency on the [`pathtools`](https://github.com/gorakhargosh/pathtools) and instead vendored the
  `patterns.py` file from that project.
- Added the `absolute_path` function to `observers/kqueue.py` instead of importing it from `pathtools`.

See https://github.com/wandb/wandb/pull/3443 for more details.
