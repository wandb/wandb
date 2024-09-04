<div align="center">
  <img src="https://i.imgur.com/RUtiVzH.png" width="600" /><br><br>
</div>

# Weights and Biases [![PyPI](https://img.shields.io/pypi/v/wandb)](https://pypi.python.org/pypi/wandb) [![Conda (channel only)](https://img.shields.io/conda/vn/conda-forge/wandb)](https://anaconda.org/conda-forge/wandb) [![CircleCI](https://img.shields.io/circleci/build/github/wandb/wandb/main)](https://circleci.com/gh/wandb/wandb) [![Codecov](https://img.shields.io/codecov/c/gh/wandb/wandb)](https://codecov.io/gh/wandb/wandb)

Use W&B to build better models faster. Track and visualize all the pieces of your machine learning pipeline, from datasets to production machine learning models. Get started with W&B today, [sign up for an account!](https://wandb.com?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=readme)



See the [W&B Developer Guide](https://docs.wandb.ai/?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=documentation) and [API Reference Guide](https://docs.wandb.ai/ref?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=documentation) for a full technical description of the W&B platform.

&nbsp;

# Quickstart

Get started with W&B in four steps:

1. First, sign up for a [W&B account](https://wandb.ai/login?utm_source=github&utm_medium=code&utm_campaign=wandb&utm_content=quickstart).

2. Second, install the W&B SDK with [pip](https://pip.pypa.io/en/stable/). Navigate to your terminal and type the following command:

```shell
pip install wandb
```

3. Third, log into W&B:

```python
wandb.login()
```

4. Use the example code snippet below as a template to integrate W&B to your Python script:

```python
import wandb

# Start a W&B Run with wandb.init
run = wandb.init(project="my_first_project")

# Save model inputs and hyperparameters in a wandb.config object
config = run.config
config.learning_rate = 0.01

# Model training code here ...

# Log metrics over time to visualize performance with wandb.log
for i in range(10):
    run.log({"loss": ...})

# Mark the run as finished, and finish uploading all data
run.finish()
```

For example, if the preceding code was stored in a script called train.py:

```shell
python train.py
```

You will see a URL in your terminal logs when your script starts and finishes. Data is staged locally in a directory named _wandb_ relative to your script. Navigate to the W&B App to view a dashboard of your first W&B Experiment. Use the W&B App to compare multiple experiments in a unified place, dive into the results of a single run, and much more!

&nbsp;

# Integrations

Use your favorite framework with W&B. W&B integrations make it fast and easy to set up experiment tracking and data versioning inside existing projects. For more information on how to integrate W&B with the framework of your choice, see [W&B Integrations](https://docs.wandb.ai/guides/integrations) in the W&B Developer Guide.

&nbsp;

# Contribution guidelines
Weights & Biases ❤️ open source, and we welcome contributions from the community! See the [Contribution guide](https://github.com/wandb/wandb/blob/main/CONTRIBUTING.md) for more information on the development workflow and the internals of the wandb library. For wandb bugs and feature requests, visit [GitHub Issues](https://github.com/wandb/wandb/issues) or contact support@wandb.com.

&nbsp;

# Academic Researchers
Reach out to W&B Support at support@wandb.com to get a [free academic license](https://www.wandb.com/academic) for you and your research group.

&nbsp;

# W&B Community

Be a part of the growing W&B Community and interact with the W&B team in our [Discord](https://wandb.me/discord). Stay connected with the latest ML updates and tutorials with [W&B Fully Connected](https://wandb.ai/fully-connected).

&nbsp;

# License

[MIT License](https://github.com/wandb/wandb/blob/main/LICENSE)
