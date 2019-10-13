---
description: >-
  Get your script integrated quickly to see our experiment tracking and
  visualization features on your own project
---

# Quickstart

Get started logging machine learning experiments in 3 quick steps.

### 1. Install Library

Install our library in an environment using Python 3.

```text
pip install wandb
```

### 2. Create Account

Sign up for a free account in your shell.

```text
wandb login
```

Alternatively, you can go to our [sign up page](https://app.wandb.ai/login?signup=true).

### 3. Modify your training script

Add a few lines to your script to log hyperparameters and metrics.

#### 3a. Initialization

Initialize `wandb` at the beginning of your script right after the imports.

```text
# Inside my model training code
import wandb
wandb.init(project="my-project")
```

We automatically create the project for you if it doesn't exist. \(See the [wandb.init](python/library/init.md) documentation for more initialization options.\)

#### 3b. Hyperparameters \(optional\)

It's easy to save hyperparameters with the [wandb.config](python/library/config.md) object.

```text
wandb.config.dropout = 0.2
wandb.config.hidden_layer_size = 128
```

#### 3c. Logging \(optional\)

Log metrics like loss or accuracy as your model trains or log more complicated things like histograms, graphs or images with [wandb.log](python/library/log.md).

Then log a few metrics:

```text
def my_train_loop():
    for epoch in range(10):
        loss = 0 # change as appropriate :)
        wandb.log({'epoch': epoch, 'loss': loss})
```

#### 3d. Saving files \(optional\)

Anything saved in the `wandb.run.dir` directory will be uploaded to W&B and saved along with your run when it completes. This is especially convenient for saving the literal weights and biases in your model:

```text
model.save(os.path.join(wandb.run.dir, "mymodel.h5"))
```

Great! Now run your script normally and we'll sync logs in a background process. Your terminal logs, metrics, and files will be synced to the cloud along with a record of your git state if you're running from a git repo.

{% hint style="info" %}
If you're testing and want to disable wandb syncing, set the [environment variable](python/advanced-features/environment-variables.md) WANDB\_MODE=dryrun
{% endhint %}

### Examples

You can find complete examples of integrating W&B here:

* [Keras](python/frameworks/keras.md)
* [PyTorch](https://docs.wandb.com/frameworks/pytorch-example)
* [Tensorflow](https://docs.wandb.com/frameworks/tensorflow-example)

