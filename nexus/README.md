# W&B Nexus: the New "Bones" for the W&B SDK

## What is Nexus

Greetings, developers!

*What is W&B Nexus?* At the highest level, Nexus is the new "bones" for the W&B SDK.

*Why would anyone care and want to use it?* There are numerous reasons, but here are just two:
- It's faster. A lot faster. We're talking 10x faster for some operations.
- It enables clean multi-language support.

For those technical folks out there, `nexus` is a Golang reimplementation of the W&B SDK
internal process, `wandb service`, based on the lessons learned from the original implementation(s),
but starting from a clean slate.

## Installation

To install Nexus, you will need to run the following commands:

```bash
pip install wandb[nexus]
```

### Supported Platforms

Nexus is currently supported on the following platforms:

- Linux (x86_64)
- macOS (x86_64)
- macOS (arm64)
- Windows (x86_64)

If you are using a different platform, you can build Nexus from source by following the
instructions in the [contributing guide](docs/contributing.md#installing-nexus).
Please also open a [GitHub issue](https://github.com/wandb/wandb/issues/new/choose)
to let us know that you are interested in using Nexus on
your platform, and we will prioritize adding support for it.

## Contributing

Please read our [contributing guide](docs/contributing.md) to learn to set up
your development environment and how to contribute to the codebase.

## Feedback
We are very much looking forward for your feedback, especially bug reports!
Please open a [GitHub issue](https://github.com/wandb/wandb/issues/new/choose)
if you encounter an error.

## Feature Parity Status

The following table shows the current status of feature parity between the current W&B SDK.

Status legend:
- ✅: Available: The feature is relatively stable and ready for use
- 🚧: In Development: The feature is available, but may be unstable or incomplete.
- ❌: Not Available: The feature is not yet available.

| Category    | Feature           | Status     |
|-------------|-------------------|------------|
| Experiments |                   |            |
|             | `init`            | ✅          |
|             | `log`             | 🚧[^E.1]   |
|             | `log_artifact`    | ❌[^E.2]    |
|             | `log_code`        | ❌[^E.3]    |
|             | `config`          | ✅          |
|             | `summary`         | 🚧[^E.4]   |
|             | `define_metric`   | 🚧[^E.5]   |
|             | `tags`            | ✅          |
|             | `notes`           | ✅          |
|             | `name`            | ✅          |
|             | `alert`           | ✅          |
|             | `save`            | 🚧[^E.6]   |
|             | `restore`         | ✅          |
|             | `mark_preempting` | ✅          |
|             | resume            | ✅          |
|             | reinit            | ✅          |
|             | Grouping          | ✅          |
|             | anonymous mode    | ?          |
|             | offline mode      | ✅          |
|             | disabled mode     | ✅          |
|             | multiprocessing   | ✅          |
|             | TensorBoard sync  | ❌          |
|             | console logging   | 🚧[^E.7]   |
|             | system metrics    | 🚧[^E.8]   |
|             | system info       | ✅          |
|             | code saving       | 🚧[^E.9]   |
|             | Settings          | 🚧[^E.10]  |
| Login       |                   |            |
|             | default entity    | ✅          |
|             | team entity       | ✅          |
|             | service account   | ✅          |
| Public API  |                   | 🚧[^PA.1]  |
| CLI         |                   | 🚧[^CLI.1] |
| Artifacts   |                   | ❌[^A.1]    |
| Launch      |                   | ❌[^L.1]    |
| Sweeps      |                   | 🚧[^S.1]   |

[^E.1]: `wandb.Table` is not supported. Requires Artifacts support.
[^E.2]: `log_artifact` is not yet supported. Requires Artifacts support.
[^E.3]: `log_code` is not yet supported. Requires Artifacts support.
[^E.4]: TODO
[^E.5]: `define_metric` only supports default summary.
[^E.6]: `save` only support `now` and `end` policy. `live` policy will be treated as `end`.
[^E.7]: TODO
[^E.8]: Supported system metrics: CPU, Memory, Disk, Network, NVIDIA GPU.
[^E.9]: Automatic code saving in Notebooks is not yet supported. Requires Artifacts support.
[^E.10]: TODO: list unsupported settings.
    (`anonymous`, `_flow_control*`, `_stats_open_metrics_endpoints`, ...)
[^PA.1]: The public API works, but uses the current Python backend under the hood.
    Expect the public API to be rewritten to use the new backend.
[^A.1]: Artifacts support is not yet available.
[^CLI.1]: The CLI works, but uses the current Python backend under the hood for some
    commands. Expect the CLI to be rewritten to use the new backend.
[^L.1]: Launch is not yet supported. Requires Artifacts support.
[^S.1]: TODO