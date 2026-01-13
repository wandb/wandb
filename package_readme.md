<div align="center">
  <img src="https://i.imgur.com/dQLeGCc.png" width="600" /><br><br>
</div>

<p align="center">
<a href="https://pypi.python.org/pypi/wandb"><img src="https://img.shields.io/pypi/v/wandb" /></a>
<a href="https://anaconda.org/conda-forge/wandb"><img src="https://img.shields.io/conda/vn/conda-forge/wandb" /></a>
<a href="https://pypi.python.org/pypi/wandb"><img src="https://img.shields.io/pypi/pyversions/wandb" /></a>
<a href="https://circleci.com/gh/wandb/wandb"><img src="https://img.shields.io/circleci/build/github/wandb/wandb/main" /></a>
<a href="https://codecov.io/gh/wandb/wandb"><img src="https://img.shields.io/codecov/c/gh/wandb/wandb" /></a>
</p>
<p align='center'>
<a href="https://colab.research.google.com/github/wandb/examples/blob/master/colabs/intro/Intro_to_Weights_%26_Biases.ipynb"><img src="https://colab.research.google.com/assets/colab-badge.svg" /></a>
</p>

Use W&B to build better models faster. Track and visualize all the pieces of your machine learning pipeline, from datasets to production machine learning models. Get started with W&B today, [sign up for a W&B account](https://wandb.com?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=readme)!

<br>

Building an LLM app? Track, debug, evaluate, and monitor LLM apps with [Weave](https://wandb.github.io/weave?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=readme), our new suite of tools for GenAI.

&nbsp;

# Documentation

See the [W&B Developer Guide](https://docs.wandb.ai/?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=documentation) and [API Reference Guide](https://docs.wandb.ai/training/api-reference#api-overview?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=documentation) for a full technical description of the W&B platform.

&nbsp;

# Quickstart

Install W&B to track, visualize, and manage machine learning experiments of any size.

## Install the wandb library

```shell
pip install wandb
```

## Sign up and create an API key

Sign up for a [W&B account](https://wandb.ai/login?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=quickstart). Optionally, use the `wandb login` CLI to configure an API key on your machine. You can skip this step -- W&B will prompt you for an API key the first time you use it.

## Create a machine learning training experiment

In your Python script or notebook, initialize a W&B run with `wandb.init()`.
Specify hyperparameters and log metrics and other information to W&B.

```python
import wandb

# Project that the run is recorded to
project = "my-awesome-project"

# Dictionary with hyperparameters
config = {"epochs" : 1337, "lr" : 3e-4}

# The `with` syntax marks the run as finished upon exiting the `with` block,
# and it marks the run "failed" if there's an exception.
#
# In a notebook, it may be more convenient to write `run = wandb.init()`
# and manually call `run.finish()` instead of using a `with` block.
with wandb.init(project=project, config=config) as run:
    # Training code here

    # Log values to W&B with run.log()
    run.log({"accuracy": 0.9, "loss": 0.1})
```

Visit [wandb.ai/home](https://wandb.ai/home) to view recorded metrics such as accuracy and loss and how they changed during each training step. Each run object appears in the Runs column with generated names.

&nbsp;

# Integrations

W&B [integrates](https://docs.wandb.ai/models/integrations) with popular ML frameworks and libraries making it fast and easy to set up experiment tracking and data versioning inside existing projects.

For developers adding W&B to a new framework, follow the [W&B Developer Guide](https://docs.wandb.ai/models/integrations/add-wandb-to-any-library).

&nbsp;

# W&B Hosting Options

Weights & Biases is available in the cloud or installed on your private infrastructure. Set up a W&B Server in a production environment in one of three ways:

1. [Multi-tenant Cloud](https://docs.wandb.ai/platform/hosting/hosting-options/multi_tenant_cloud?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=hosting): Fully managed platform deployed in W&B’s Google Cloud Platform (GCP) account in GCP’s North America regions.
2. [Dedicated Cloud](https://docs.wandb.ai/platform/hosting/hosting-options/dedicated_cloud?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=hosting): Single-tenant, fully managed platform deployed in W&B’s AWS, GCP, or Azure cloud accounts. Each Dedicated Cloud instance has its own isolated network, compute and storage from other W&B Dedicated Cloud instances.
3. [Self-Managed](https://docs.wandb.ai/platform/hosting/hosting-options/self-managed?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=hosting): Deploy W&B Server on your AWS, GCP, or Azure cloud account or within your on-premises infrastructure.

See the [Hosting documentation](https://docs.wandb.ai/guides/hosting?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=hosting) in the W&B Developer Guide for more information.

&nbsp;

# Python Version Support

We are committed to supporting our minimum required Python version for _at least_ six months after its official end-of-life (EOL) date, as defined by the Python Software Foundation. You can find a list of Python EOL dates [here](https://devguide.python.org/versions/).

When we discontinue support for a Python version, we will increment the library’s minor version number to reflect this change.

&nbsp;

# Contribution guidelines

Weights & Biases ❤️ open source, and we welcome contributions from the community! See the [Contribution guide](https://github.com/wandb/wandb/blob/main/CONTRIBUTING.md) for more information on the development workflow and the internals of the wandb library. For wandb bugs and feature requests, visit [GitHub Issues](https://github.com/wandb/wandb/issues) or contact support@wandb.com.

&nbsp;

# W&B Community

Be a part of the growing W&B Community and interact with the W&B team in our [Discord](https://wandb.me/discord). Stay connected with the latest ML updates and tutorials with [W&B Fully Connected](https://wandb.ai/fully-connected).

&nbsp;

# License

[MIT License](https://github.com/wandb/wandb/blob/main/LICENSE)
