# Overview

Use W&B to manage hyperparameter sweeps. These are useful for efficiently finding the best version of your model.

### Getting Started

#### Initialize the project

In your project repo, initialize your project from the command line:

```text
wandb init
```

#### Create a sweep configuration

The sweep configuration file specifies your training script, parameter ranges, search strategy and stopping criteria.

Here's an example config file:

```text
program: train.py
method: bayes
metric:
  name: val_loss
  goal: minimize
parameters:
  learning-rate:
    min: 0.001
    max: 0.1
  optimizer:
    values: ["adam", "sgd"]
```

#### Initialize the sweep

Run this from the command line to get a SWEEP\_ID and a URL to track all your runs.

```text
wandb sweep sweep.yaml # prints out SWEEP_ID.
```

#### Run agent\(s\)

Run one or more wandb agents with the SWEEP\_ID. Agents will request parameters from the parameter server and launch your training script.

```text
wandb agent SWEEP_ID
```

