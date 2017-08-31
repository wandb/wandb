# Weights and Biases

[![ci](https://circleci.com/gh/wandb/client.svg?style=svg)](https://circleci.com/gh/wandb/client) [![pypi](https://img.shields.io/pypi/v/wandb.svg)](https://pypi.python.org/pypi/wandb) [![coveralls](https://coveralls.io/repos/github/wandb/client/badge.svg?branch=master)](https://coveralls.io/github/wandb/client?branch=master)

A CLI and library for interacting with the Weights and Biases API.  Sign up for an account at [wandb.ai](https://wandb.ai)

## Features

* Keep a history of your weights and models from every training run
* Store all configuration parameters used in a training run
* Associate version control with your training runs
* Search and visualize training runs in a project
* Sync canonical models in your preferred format

## Usage

### CLI:

```shell
cd myproject
# Initialize a directory
wandb init
# Push files to W&B
wandb push bucket model.json weights.h5
# Sync training logs and push files when they change
./my_training.py | wandb bucket model.json weights.h5
# Manage configuration
wandb config set epochs=30
```

### Client:

```python
import wandb
conf = wandb.sync(["weights.h5", "model.json"], config={'existing': 'config'})

if conf.turbo:
    print("TURBO MODE!!!")
```

Detailed usage can be found in our [documentation](http://wb-client.readthedocs.io/en/latest/usage.html).
