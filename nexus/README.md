# Project Nexus: A New Backend for the W&B SDK

[![PyPI version](https://badge.fury.io/py/wandb-core.svg)](https://badge.fury.io/py/wandb-core)
[![PyPI - License](https://img.shields.io/pypi/l/wandb-core)]()

## What is it all about?

Good News, Everyone!

We have built a new backend for the W&B SDK that is more robust, performant, and versatile!

## How do I use it?

All you need is to have the `wandb-core` package installed into your environment. `wandb` will
pick it up and use it automatically:

```bash
pip install -U wandb wandb-core
```

Note: you will need `wandb>=0.16.0`.

### Supported Platforms

- Linux:`x86_64`, `aarch64`
- macOS: `x86_64`, `arm64`
- Windows `amd64`

If you are using a different platform, you can build `wandb-core` from sources by following the
instructions in the [contributing guide](docs/contributing.md#installing-nexus).
Please also open a [GitHub issue](https://github.com/wandb/wandb/issues/new/choose)
to let us know that you are interested in using it on
your platform, and we will prioritize adding support for it.

### How do I fall back to the previous version of the SDK backend?

Just uninstall `wandb-core` from your environment.

```bash
pip uninstall wandb-core
```

## Contributing

Please read our [contributing guide](docs/contributing.md) to learn to set up
your development environment and how to contribute to the codebase.

## Feedback
Please give Nexus a try and let us know what you think, we believe it is worth it!

We are very much looking forward to your feedback, especially bug reports!
Please open a [GitHub issue](https://github.com/wandb/wandb/issues/new/choose)
if you encounter an error, and mention that you are using `wandb-core`.

## Feature Support Status

The following table shows the status of the feature support as of `wandb-core` version `0.17.0b2`.

Status legend:
- ✅: Available: The feature is relatively stable and ready for use.
- 🚧: In Development: The feature is available, but may be unstable or incomplete.
- ❌: Not Available: The feature is not yet available.

| Category    | Feature           | Status     |
|-------------|-------------------|------------|
| Experiments |                   |            |
|             | `init`            | ✅[^E.1]    |
|             | `log`             | ✅          |
|             | `log_artifact`    | ✅          |
|             | `log_code`        | ✅          |
|             | `config`          | ✅          |
|             | `summary`         | ✅          |
|             | `define_metric`   | 🚧[^E.5]   |
|             | `tags`            | ✅          |
|             | `notes`           | ✅          |
|             | `name`            | ✅          |
|             | `alert`           | ✅          |
|             | `save`            | ✅          |
|             | `restore`         | ✅          |
|             | `mark_preempting` | ✅          |
|             | resume            | ✅          |
|             | reinit            | ✅          |
|             | Media             | ✅          |
|             | Grouping          | ✅          |
|             | anonymous mode    | ✅          |
|             | offline mode      | ✅          |
|             | disabled mode     | ✅          |
|             | multiprocessing   | ✅          |
|             | TensorBoard sync  | ❌          |
|             | console logging   | 🚧[^E.8]   |
|             | system metrics    | 🚧[^E.9]   |
|             | system info       | ✅          |
|             | auto code saving  | ✅          |
|             | Settings          | 🚧[^E.12]  |
| Login       |                   |            |
|             | default entity    | ✅          |
|             | team entity       | ✅          |
|             | service account   | 🚧          |
| CLI         |                   | 🚧[^CLI.1] |
| Artifacts   |                   | ✅          |
| Launch      |                   | ❌[^L.1]    |
| Sweeps      |                   | 🚧[^S.1]   |

[^E.1]: `sync_tensorboard` requires TensorBoard sync support.
[^E.5]: `define_metric` only supports default summary.
[^E.8]: Only raw console logging is supported.
[^E.9]: Supported system metrics: CPU, Memory, Disk, Network, NVIDIA GPU.
[^E.12]: TODO: list unsupported settings.
    (`anonymous`, `_flow_control*`, `_stats_open_metrics_endpoints`, ...)
[^CLI.1]: The CLI works, but uses the current Python backend under the hood for some
    commands. Expect the CLI to be rewritten to use the new backend.
[^L.1]: Launch is not yet supported.
[^S.1]: Requires verification.
