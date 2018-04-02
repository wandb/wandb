<div align="center">
  <img src="https://app.wandb.ai/logo.svg" width="350" /><br><br>
</div>

# Weights and Biases [![ci](https://circleci.com/gh/wandb/client.svg?style=svg)](https://circleci.com/gh/wandb/client) [![pypi](https://img.shields.io/pypi/v/wandb.svg)](https://pypi.python.org/pypi/wandb)

The **Weights and Biases** client is an open source library, CLI (wandb), and local web application for organizing and analyzing your machine learning experiments. Think of it as a framework-agnostic lightweight TensorBoard that persists additional information such as the state of your code, system metrics, and configuration parameters.

## Local Features

*   Store config parameters used in a training run
*   Associate version control with your training runs
*   Search, compare, and visualize training runs
*   Analyze system usage metrics alongside runs

## Cloud Features

*   Collaborate with team members
*   Run parameter sweeps
*   Persist runs forever

## Quickstart

```shell
pip install wandb
```

In your training script:

```python
import wandb
from wandb.keras import WandbCallback
# Your custom arguments defined here
args = ...

run = wandb.init(config=args)
run.config["more"] = "custom"

def training_loop():
    while True:
        # Do some machine learning
        epoch, loss, val_loss = ...
        # Framework agnostic / custom metrics
        run.history.add({"epoch": epoch, "loss": loss, "val_loss": val_loss})
        # Keras metrics
        model.fit(..., callbacks=[WandbCallback()])
```

Running your training script will save data in a directory named _wandb_ relative to your training script. To view your runs, call `wandb board` from the same directory as your training script.

<p align="center">
    <img src="https://github.com/wandb/client/raw/master/docs/screenshot.jpg?raw=true" alt="Runs screenshot" style="max-width:100%;">
</p>

## Cloud Usage

[Signup](https://app.wandb.ai/login?invited) for an account, then run `wandb init` from the directory with your training script. You can checkin _wandb/settings_ to version control to enable other users on your team to share experiments. Run your script with `wandb run my_script.py` and all metadata will be synced to the cloud.

## Detailed Usage

Framework specific and detailed usage can be found in our [documentation](http://docs.wandb.com/).

## Development

See https://github.com/wandb/client/blob/master/DEVELOPMENT.md
