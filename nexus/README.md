# W&B Nexus: A New Backend for the W&B SDK

[![PyPI version](https://badge.fury.io/py/wandb-core.svg)](https://badge.fury.io/py/wandb-core)
[![PyPI - License](https://img.shields.io/pypi/l/wandb-core)]()

## What is Nexus?

Greetings, developers!

*What is Project Nexus?* At the highest level, Nexus is a new backend for the W&B SDK.

*Why would anyone care and want to use it?* There are multiple reasons, but here are just two:
- It's faster. A lot faster. We're talking orders of magnitude faster for some operations.
- It enables clean multi-language support.

`nexus` is a Golang reimplementation of the W&B SDK internal process, `wandb service`,
based on the lessons learned from the original implementation(s),
but starting from a clean slate.

## Installation

To install Nexus, you will need to run the following commands:

```bash
pip install "wandb[nexus]" --pre
```

### Supported Platforms

Nexus is currently supported on the following platforms:

- Linux:`x86_64`, `aarch64`
- macOS: `x86_64`, `arm64`
- Windows `amd64`

If you are using a different platform, you can build Nexus from the source by following the
instructions in the [contributing guide](docs/contributing.md#installing-nexus).
Please also open a [GitHub issue](https://github.com/wandb/wandb/issues/new/choose)
to let us know that you are interested in using Nexus on
your platform, and we will prioritize adding support for it.

## Usage example

While Nexus is still in development, you need to explicitly opt-in to use it.

```python
import wandb

wandb.require("nexus")

# Your code here using the W&B SDK
```

## Contributing

Please read our [contributing guide](docs/contributing.md) to learn to set up
your development environment and how to contribute to the codebase.

## Feedback
Please give Nexus a try and let us know what you think, we believe it is worth it!

We are very much looking forward to your feedback, especially bug reports.
Please open a [GitHub issue](https://github.com/wandb/wandb/issues/new/choose)
if you encounter an error, mention that you are using Nexus.

## Feature Parity Status

The following table shows the status of the feature parity
between the current W&B SDK and Nexus for version `0.16.0b1`.

Status legend:
- ✅: Available: The feature is relatively stable and ready for use.
- 🚧: In Development: The feature is available, but may be unstable or incomplete.
- ❌: Not Available: The feature is not yet available.

| Category    | Feature           | Status        |
|-------------|-------------------|---------------|
| Experiments |                   |               |
|             | `init`            | ✅[^E.1][^E.6] |
|             | `log`             | ✅             |
|             | `log_artifact`    | ✅             |
|             | `log_code`        | ✅             |
|             | `config`          | ✅             |
|             | `summary`         | ✅             |
|             | `define_metric`   | 🚧[^E.5]      |
|             | `tags`            | ✅             |
|             | `notes`           | ✅             |
|             | `name`            | ✅             |
|             | `alert`           | ✅             |
|             | `save`            | 🚧[^E.6]      |
|             | `restore`         | ✅             |
|             | `mark_preempting` | ✅             |
|             | resume            | ✅             |
|             | reinit            | ✅             |
|             | Media             | ✅             |
|             | Grouping          | ✅             |
|             | anonymous mode    | ✅             |
|             | offline mode      | ✅             |
|             | disabled mode     | ✅             |
|             | multiprocessing   | ✅             |
|             | TensorBoard sync  | ❌             |
|             | console logging   | 🚧[^E.8]      |
|             | system metrics    | 🚧[^E.9]      |
|             | system info       | ✅             |
|             | auto code saving  | 🚧[^E.6]      |
|             | Settings          | 🚧[^E.12]     |
| Login       |                   |               |
|             | default entity    | ✅             |
|             | team entity       | ✅             |
|             | service account   | ✅             |
| CLI         |                   | 🚧[^CLI.1]    |
| Artifacts   |                   | 🚧[^A.1]      |
| Launch      |                   | ❌[^L.1]       |
| Sweeps      |                   | 🚧[^S.1]      |

[^E.1]: `sync_tensorboard` requires TensorBoard sync support.
[^E.5]: `define_metric` only supports default summary.
[^E.6]: Only `now` and `end` policies are supported. `live` policy will be treated as `end`.
[^E.8]: Only raw console logging is supported.
[^E.9]: Supported system metrics: CPU, Memory, Disk, Network, NVIDIA GPU.
[^E.12]: TODO: list unsupported settings.
    (`anonymous`, `_flow_control*`, `_stats_open_metrics_endpoints`, ...)
[^CLI.1]: The CLI works, but uses the current Python backend under the hood for some
    commands. Expect the CLI to be rewritten to use the new backend.
[^A.1]: Artifacts are partially supported. Expect full support in a next pre-release.
[^L.1]: Launch is not yet supported.
[^S.1]: Requires verification.
