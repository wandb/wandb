<div align="center">
  <img src="https://app.wandb.ai/logo.svg" width="350" /><br><br>
</div>

# Weights and Biases [![ci](https://circleci.com/gh/wandb/client.svg?style=svg)](https://circleci.com/gh/wandb/client) [![pypi](https://img.shields.io/pypi/v/wandb.svg)](https://pypi.python.org/pypi/wandb)

The **Weights and Biases** client is a library, CLI (wandb), and local web application for organizing and analyzing your machine learning experiments. Think of it as a framework-agnostic lightweight TensorBoard that persists additional information such as the state of your code, system metrics, and configuration parameters. You can optionally sync all of this data to the cloud to enable better collaboration with your team.

## Features

* Store config parameters used in a training run
* Associate version control with your training runs
* Search, compare, and visualize training runs
* Analyze system usage metrics alongside runs
* Optionally persist runs to the cloud

## Quickstart

```shell
pip install wandb
```

In your training script:

```python
import wandb
# Your custom arguments defined here
args = ...

run = wandb.init()
run.config.update(args)
run.config["custom"] = "parameter"

def training_loop():
    while True:
        # Do some machine learning
        epoch, loss = ...
        run.history.add({"epoch": epoch, "loss": loss})
```

Running your script normally will save run data in a directory named `wandb` relative to your training script. To view your runs, call the following from the same directory as your training script:

```shell
wandb board
```

## Usage

Framework specific and detailed usage can be found in our [documentation](http://docs.wandb.com/).
