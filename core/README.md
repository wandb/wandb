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

`wandb-core` is a new and improved backend for the W&B SDK that is more performant, versatile, and robust.

**Upgrade now and experience:**

* 🚀 **Logging performance:** Experience up to 88% performance improvements when logging with multiple processes.
* 🤏 **Reduced resource consumption:** Lower memory footprint allows you to run more experiments on your machines.
* 📊 **Improved Table logging:** Experience up to 40% faster table logging performance!
* ⚡ **Faster startups & shutdowns:** Enjoy up to 36% faster startup and shutdown times.
* ⏩ **Enhanced artifact handling:** Experience up to 33% faster Artifact uploads speed and up to 27% faster Artifact retrieval!
* 🌐 **Faster offline sync:** Keep your long-running experiments synced effortlessly with improved offline speeds.

See our [benchmark analysis](https://github.com/wandb/wandb/blob/main/tools/bench/bench.md) for more information on performance improvements.

## Quickstart
Get started with wandb-core in four steps:

1. First, sign up for a [free W&B account](https://wandb.ai/login?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=quickstart).

2. Second, install the W&B SDK with [pip](https://pip.pypa.io/en/stable/). Navigate to your terminal and type the following command:

```bash
pip install wandb
```
***Note: ensure you have `wandb>=0.17.5`.***

3. Third, log into W&B:

```python
wandb.login()
```

4. Use the example code snippet below as a template to integrate W&B to your Python script:

To start using `wandb-core`, add `wandb.require("core")` to your script after importing `wandb`:

```python
import wandb

# Add requirement for wandb core
wandb.require("core")

# Start a W&B Run with wandb.init
run = wandb.init(project="my_first_project")

# Save model inputs and hyperparameters in a wandb.config object
config = run.config
config.learning_rate = 0.01

# Model training code here ...

# Log metrics over time to visualize performance with wandb.log
for i in range(10):
    run.log({"loss": loss})

run.finish()
```
<p align='center'>
<a href="https://colab.research.google.com/github/wandb/examples/blob/master/colabs/intro/Intro_to_Weights_%26_Biases.ipynb"><img src="https://colab.research.google.com/assets/colab-badge.svg" /></a>
</p>



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

To revert to the old SDK backend, simply remove `wandb.require("core")` from your script.

### Feature support status

<details>
<summary>Click to expand for feature support status in `wandb-core`</summary>

Status legend:
- ✅: Available: The feature is relatively stable and ready for use.
- 🚧: In Development: The feature is available but may be unstable or incomplete.
- ❌: Not Available: The feature is not yet available.

| Category    | Feature           | Status           |
|-------------|-------------------|------------------|
| Experiments |                   |                  |
|             | `init`            | ✅               |
|             | `log`             | ✅               |
|             | `log_artifact`    | ✅               |
|             | `log_code`        | ✅               |
|             | `config`          | ✅               |
|             | `summary`         | ✅               |
|             | `define_metric`   | ✅               |
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
|             | TensorBoard sync  | ✅               |
|             | console logging   | ✅[^E.1]         |
|             | system metrics    | ✅[^E.2]         |
|             | system info       | ✅               |
|             | auto code saving  | ✅               |
|             | Forking           | ✅               |
|             | Rewind            | ✅               |
|             | Settings          | ✅               |
| Login       |                   |                  |
|             | default entity    | ✅               |
|             | team entity       | ✅               |
|             | service account   | ✅               |
| CLI         |                   | ✅               |
| Artifacts   |                   | ✅               |
| Sweeps      |                   | ✅               |
| Launch      |                   | ✅               |

[^E.1]: Only raw console logging is supported.
[^E.2]: Supported system metrics: CPU, Memory, Disk, Network, NVIDIA GPU, AMD GPU, Apple GPU.
<details>
