<p align="center">
  <img src="../assets/logo-dark.svg#gh-dark-mode-only" width="600" alt="Weights & Biases" />
  <img src="../assets/logo-light.svg#gh-light-mode-only" width="600" alt="Weights & Biases" />
</p>

<p align='center'>
<a href="https://pypi.org/project/wandb-core/"><img src="https://img.shields.io/pypi/v/wandb" /></a>
<a href="https://app.circleci.com/pipelines/github/wandb/core"><img src="https://img.shields.io/circleci/build/github/wandb/wandb/main" /></a>
<a href="https://app.codecov.io/gh/wandb/wandb/tree/main/core"><img src="https://img.shields.io/codecov/c/gh/wandb/wandb" /></a>
</p>
<p align='center'>
<a href="https://colab.research.google.com/github/wandb/examples/blob/master/colabs/intro/Intro_to_Weights_%26_Biases.ipynb"><img src="https://colab.research.google.com/assets/colab-badge.svg" /></a>
</p>

# `wandb-core`: A new backend for the W&B SDK

## Introduction

`wandb-core` is a new and improved backend for the W&B SDK that is more performant, versatile, and robust. `wandb-core` is enabled by default with `wandb>=0.18.0`.

**`wandb-core` enables:**

* 🚀 **Logging performance:** Experience up to 88% performance improvements when logging with multiple processes.
* 🤏 **Reduced resource consumption:** Lower memory footprint allows you to run more experiments on your machines.
* 📊 **Improved Table logging:** Experience up to 40% faster table logging performance!
* ⚡ **Faster startups & shutdowns:** Enjoy up to 36% faster startup and shutdown times.
* ⏩ **Enhanced artifact handling:** Experience up to 33% faster Artifact uploads speed and up to 27% faster Artifact retrieval!
* 🌐 **Faster offline sync:** Keep your long-running experiments synced effortlessly with improved offline speeds.

See our [benchmark analysis](https://github.com/wandb/wandb/blob/main/tools/bench/bench.md) for more information on performance improvements.

## Contributing
Your contributions are welcome! Please follow our [contributing guide](https://github.com/wandb/wandb/blob/main/CONTRIBUTING.md) for more details.

## Feedback and bug reporting
We're eager to hear your thoughts on `wandb-core`. Your feedback and bug reports are invaluable. If you encounter any issues, please raise a [GitHub issue](https://github.com/wandb/wandb/issues/new/choose) and mention your use of `wandb-core`.

## Compatibility

### Platform

`wandb-core` is pre-built for the following platforms:

- Linux: `x86_64`, `aarch64`
- macOS: `x86_64`, `arm64`
- Windows: `amd64`

If it is not supported for your platform, you will see an error if you try to start a run. If you're interested in support for additional platforms, please inform us by opening a [GitHub issue](https://github.com/wandb/wandb/issues/new/choose). Your feedback helps us prioritize new platform support.

### W&B Server compatibility

`wandb-core` is compatible with our production and dedicated cloud deployments as well as
[W&B Server](https://docs.wandb.ai/guides/hosting) versions `>=0.40.0`.

### Disabling `wandb-core`

If you need to revert to the previous SDK backend while using `wandb >= 0.18.0`, you can do so by following one of these steps:

**Option 1**: Add the following line to your script:
```python
wandb.require("legacy-service")
```
**Option 2**: Alternatively, set the environment variable WANDB__REQUIRE_LEGACY_SERVICE to TRUE:

```shell
export WANDB__REQUIRE_LEGACY_SERVICE=TRUE
```
**Note:**
* Starting from version 0.18.0, the `wandb-core` service is the default runtime service. As a result, calling `wandb.require("core")` is unnecessary and has no effect in `wandb>=0.18.0`.
