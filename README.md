# Weights and Biases

[![ci](https://circleci.com/gh/wandb/client.svg?style=svg)](https://circleci.com/gh/wandb/client) [![pypi](https://img.shields.io/pypi/v/wandb.svg)](https://pypi.python.org/pypi/wandb) [![coveralls](https://coveralls.io/repos/github/wandb/client/badge.svg?branch=master)](https://coveralls.io/github/wandb/client?branch=master)

A CLI and library for interacting with the Weights and Biases API.  Sign up for an account at [wandb.ai](https://wandb.ai)

## Features

This library provides a CLI and python library for the [Weights & Biases](https://wanbd.ai) machine learning model management platform.  It simplifies uploading or downloading files via the command line or directly in your training code.

## Usage

CLI:

```shell
cd myproject
# Initialize a directory
wandb init
# Push files to W&B
wandb push bucket model.json weights.h5
# Pull files from canonical models
wandb pull zoo/inception-v4
# Sync training logs and push files when they change
./my_training.py | wandb project/bucket model.json weights.h5
# Manage configuration
wandb config set epochs=30
```

Client:

```python
import wandb
conf = wandb.Config()
client = wandb.Api()

if conf.turbo:
    print("TURBO MODE!!!")

client.push("my_model", files=[open("some_file", "rb")])
```

Detailed usage can be found in our [documentation](http://wb-client.readthedocs.io/en/latest/usage.html).