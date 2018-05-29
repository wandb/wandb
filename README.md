<div align="center">
  <img src="https://app.wandb.ai/logo.svg" width="350" /><br><br>
</div>

# Weights and Biases [![ci](https://circleci.com/gh/wandb/client.svg?style=svg)](https://circleci.com/gh/wandb/client) [![pypi](https://img.shields.io/pypi/v/wandb.svg)](https://pypi.python.org/pypi/wandb)

The **W&B** client is an open source library and CLI (wandb) for organizing and analyzing your machine learning experiments. Think of it as a framework-agnostic lightweight TensorBoard that persists additional information such as the state of your code, system metrics, and configuration parameters.

## Features

* Store config parameters used in a training run
* Associate version control with your training runs
* Search, compare, and visualize training runs
* Analyze system usage metrics alongside runs
* Collaborate with team members
* Run parameter sweeps
* Persist runs forever

## Quickstart

```shell
pip install wandb
```

In your training script:

```python
import wandb
# Your custom arguments defined here
args = ...

run = wandb.init(config=args)
run.config["more"] = "custom"

def training_loop():
    while True:
        # Do some machine learning
        epoch, loss, val_loss = ...
        # Framework agnostic / custom metrics
        wandb.log({"epoch": epoch, "loss": loss, "val_loss": val_loss})
```

## Running your script

Run `wandb signup` from the directory of your training script. If you already have an account, you can run `wandb init` to initialize a new directory. You can checkin _wandb/settings_ to version control to share your project with other users.

Run your script with `python my_script.py` and all metadata will be synced to the cloud. Data is staged locally in a directory named _wandb_ relative to your script. If you want to test your script without syncing to the cloud you can run `wandb off`.

<p align="center">
    <img src="https://github.com/wandb/client/raw/master/docs/screenshot.jpg?raw=true" alt="Runs screenshot" style="max-width:100%;">
</p>

## Detailed Usage

Framework specific and detailed usage can be found in our [documentation](http://docs.wandb.com/).
