# wandb-core: A New Backend for the W&B SDK

## Introduction

Good News, Everyone! We've developed a new and improved backend for the W&B SDK that is
more performant, versatile, and robust.

## Getting Started

To start using the new backend, add `wandb.require("core")` to your script after importing `wandb`:

```python
import wandb

wandb.require("core")
```

Note: ensure you have `wandb>=0.17.0`.

### Platform Compatibility

`wandb-core` is pre-built for the following platforms:

- Linux:`x86_64`, `aarch64`
- macOS: `x86_64`, `arm64`
- Windows `amd64`

For other platforms, build `wandb-core` from the source as outlined in our [contributing guide](docs/contributing.md#installing-wandb-core). If you're interested in support for additional platforms, please inform us by opening a [GitHub issue](https://github.com/wandb/wandb/issues/new/choose). Your feedback helps us prioritize new platform support.

### W&B Server Compatibility

`wandb-core` is compatible with our production and dedicated cloud deployments as well as
[W&B Server](https://docs.wandb.ai/guides/hosting) versions `>=0.40.0`.

### Switching Back to the Old SDK Backend

To revert to the old SDK backend, remove `wandb.require("core")` from your script.

## Contributing

Your contributions are welcome! Please follow our [contributing guide](https://github.com/wandb/wandb/blob/main/CONTRIBUTING.md) for more details.

## Feedback and Bug Reporting
We're eager to hear your thoughts on `wandb-core`. Your feedback, especially bug reports, is invaluable. If you encounter any issues, please raise a [GitHub issue](https://github.com/wandb/wandb/issues/new/choose) and mention your use of `wandb-core`.

## Feature Support Status

Below is an overview of the feature support status in `wandb-core`.

Status legend:
- ✅: Available: The feature is relatively stable and ready for use.
- 🚧: In Development: The feature is available but may be unstable or incomplete.
- ❌: Not Available: The feature is not yet available.

| Category    | Feature           | Status           |
|-------------|-------------------|------------------|
| Experiments |                   |                  |
|             | `init`            | ✅[^E.1]         |
|             | `log`             | ✅               |
|             | `log_artifact`    | ✅               |
|             | `log_code`        | ✅               |
|             | `config`          | ✅               |
|             | `summary`         | ✅               |
|             | `define_metric`   | 🚧[^E.5]         |
|             | `tags`            | ✅               |
|             | `notes`           | ✅               |
|             | `name`            | ✅               |
|             | `alert`           | ✅               |
|             | `save`            | ✅               |
|             | `restore`         | ✅               |
|             | `mark_preempting` | ✅               |
|             | resume            | ✅               |
|             | reinit            | ✅               |
|             | Media             | ✅               |
|             | Grouping          | ✅               |
|             | anonymous mode    | ✅               |
|             | offline mode      | ✅               |
|             | disabled mode     | ✅               |
|             | multiprocessing   | ✅               |
|             | TensorBoard sync  | 🚧[^E.1]         |
|             | console logging   | ✅[^E.8]         |
|             | system metrics    | ✅[^E.9]         |
|             | system info       | ✅               |
|             | auto code saving  | ✅               |
|             | Settings          | 🚧[^E.12]        |
| Login       |                   |                  |
|             | default entity    | ✅               |
|             | team entity       | ✅               |
|             | service account   | 🚧               |
| CLI         |                   |                  |
|             | `sync`            | ✅[^E.1][^CLI.1] |
|             | `<other commands>`| 🚧[^CLI.2]       |
| Artifacts   |                   | ✅               |
|             | caching           | ✅               |
|             | partial downloads | ❌               |
| Sweeps      |                   | ✅               |
| Launch      |                   | ✅               |

[^E.1]: `sync_tensorboard` uploads `tfevent` files to W&B, so the TensorBoard tab works, but only some types of metrics appear in native W&B charts.
[^E.5]: `define_metric` only supports default summary.
[^E.8]: Only raw console logging is supported.
[^E.9]: Supported system metrics: CPU, Memory, Disk, Network, NVIDIA GPU, AMD GPU, Apple GPU.
[^E.12]: Unsupported settings:
    (`anonymous`, `_flow_control*`, `_stats_open_metrics_endpoints`, ...)
[^CLI.1]: The command is namespaced under `wandb beta` group.
[^CLI.2]: The rest of the CLI works, but uses the old backend under the hood for some
    commands.
