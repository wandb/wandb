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
✅: Available: The feature is relatively stable and ready for use
🚧: In Development: The feature is either available, but lacking some functionality,
or has not entered development yet.

| Category   | Feature               | Status     |
|------------|-----------------------|------------|
| Run        |                       |            |
|            | `init`                | ✅          |
|            | `log`                 | ✅[^R.0]    |
|            | `config`              | ✅          |
|            | `log_artifact`        | 🚧         |
|            | `summary`             | 🚧[^R.1]   |
|            | `define_metric`       | 🚧[^R.2]   |
|            | `tags`                | ✅          |
|            | `notes`               | ✅          |
|            | multiprocessing       | ✅          |
|            | console logging       | 🚧[^R.3]   |
|            | system metrics        | 🚧[^R.4]   |
|            | system info           | ✅          |
|            | code saving           | 🚧[^R.5]   |
|            | offline mode          | ✅          |
|            | alerts                | ✅[^R.6]    |
|            | settings              | ✅[^R.7]    |
|            | resume                | ✅          |
|            | save/restore          | ✅          |
|            | TensorBoard sync      | 🚧         |
|            | mark preempting       | ✅          |
| Login      |                       |            |
|            | default entity        | ✅          |
|            | team entity           | ✅          |
|            | service account       | ✅          |
| Artifacts  |                       |            |
|            | basic artifacts       | 🚧         |
|            | incremental artifacts | 🚧         |
|            | reference artifacts   | 🚧         |
| Public API |                       | 🚧[^PA.1]  |
| CLI        |                       | 🚧[^CLI.1] |
| Launch     |                       | 🚧         |
| Sweeps     |                       | 🚧         |

[^R.0]: TODO: check if Tables work.
[^R.1]: TODO
[^R.2]: TODO
[^R.3]: TODO
[^R.4]: Supported system metrics: CPU, Memory, Disk, Network, NVIDIA GPU.
[^R.5]: Automatic code saving in Notebooks is not yet supported.
[^R.6]: It worked, need to verify.
[^R.7]: TODO: list unsupported settings.
    (`anonymous`, `_flow_control*`, `_stats_open_metrics_endpoints`, ...)
[^PA.1]: The public API works, but uses the current Python backend under the hood.
    Expect the public API to be rewritten to use the new backend.
[^CLI.1]: The CLI works, but uses the current Python backend under the hood for some
    commands. Expect the CLI to be rewritten to use the new backend.
