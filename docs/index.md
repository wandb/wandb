# Weights & Biases Documentation

## Intro

[Weights & Biases](http://wandb.com) tracks machine learning jobs in real-time, makes them reproducible, and permanently stores jobs outputs (like models).


## Quickstart - Existing Project

This explains how to quickly integrate wandb into an existing project.

First, [signup](https://app.wandb.ai/login) for a Weights & Biases account.

<br>
Next, install the Weights & Biases command line tool "wandb".
```console
$ pip install wandb
```

<br>
Initialize Weights & Biases in your project.
```console
$ cd <project_directory>
$ wandb init
```

Follow the prompts to complete the initialization process.

<br>
Then, import our Python module into your code. In your training script:
```console
import wandb
```

<br>
Finally, launch your job

```console
wandb run <train.py>
```

wandb will print a link that you can open to track the status of your job.