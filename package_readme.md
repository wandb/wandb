<div align="center">
  <img src="https://i.imgur.com/RUtiVzH.png" width="600" /><br><br>
</div>

# Weights and Biases [![PyPI](https://img.shields.io/pypi/v/wandb)](https://pypi.python.org/pypi/wandb) [![Conda (channel only)](https://img.shields.io/conda/vn/conda-forge/wandb)](https://anaconda.org/conda-forge/wandb) [![CircleCI](https://img.shields.io/circleci/build/github/wandb/wandb/master)](https://circleci.com/gh/wandb/wandb) [![Codecov](https://img.shields.io/codecov/c/gh/wandb/wandb)](https://codecov.io/gh/wandb/wandb)

Use W&B to build better models faster. Track and visualize all the pieces of your machine learning pipeline, from datasets to production models.

- Quickly identify model regressions. Use W&B to visualize results in real time, all in a central dashboard.
- Focus on the interesting ML. Spend less time manually tracking results in spreadsheets and text files.
- Capture dataset versions with W&B Artifacts to identify how changing data affects your resulting models.
- Reproduce any model, with saved code, hyperparameters, launch commands, input data, and resulting model weights.

[Sign up for a free account →](https://wandb.ai/login?signup=true)

## Features

-   Store hyper-parameters used in a training run
-   Search, compare, and visualize training runs
-   Analyze system usage metrics alongside runs
-   Collaborate with team members
-   Replicate historic results
-   Run parameter sweeps
-   Keep records of experiments available forever

[Documentation →](https://docs.wandb.com)

## Quickstart

```shell
pip install wandb
```

In your training script:

```python
import wandb

# Your custom arguments defined here
args = ...

wandb.init(config=args, project="my-project")
wandb.config["more"] = "custom"


def training_loop():
    while True:
        # Do some machine learning
        epoch, loss, val_loss = ...
        # Framework agnostic / custom metrics
        wandb.log({"epoch": epoch, "loss": loss, "val_loss": val_loss})
```

If you're already using Tensorboard or [TensorboardX](https://github.com/lanpa/tensorboardX), you can integrate with one line:

```python
wandb.init(sync_tensorboard=True)
```

## Running your script

Run `wandb login` from your terminal to signup or authenticate your machine (we store your api key in ~/.netrc). You can also set the `WANDB_API_KEY` environment variable with a key from your [settings](https://app.wandb.ai/settings).

Run your script with `python my_script.py` and all metadata will be synced to the cloud. You will see a url in your terminal logs when your script starts and finishes. Data is staged locally in a directory named _wandb_ relative to your script. If you want to test your script without syncing to the cloud you can set the environment variable `WANDB_MODE=dryrun`.

If you are using [docker](https://docker.com) to run your code, we provide a wrapper command `wandb docker` that mounts your current directory, sets environment variables, and ensures the wandb library is installed. Training your models in docker gives you the ability to restore the exact code and environment with the `wandb restore` command.

## Web Interface

[Sign up for a free account →](https://wandb.com)
[![Watch the video](https://i.imgur.com/PW0Ejlc.png)](https://youtu.be/EeqhOSvNX-A)
[Introduction video →](https://youtu.be/EeqhOSvNX-A)

## Detailed Usage

Framework specific and detailed usage can be found in our [documentation](http://docs.wandb.com/).

## Testing

To run basic test use `make test`.  More detailed information can be found at CONTRIBUTING.md.

We use [circleci](https://circleci.com) for CI.

# Academic Researchers
If you'd like a free academic account for your research group, [reach out to us →](https://www.wandb.com/academic)

We make it easy to cite W&B in your published paper. [Learn more →](https://www.wandb.com/academic)
[![](https://i.imgur.com/loKLiez.png)](https://www.wandb.com/academic)

## Community
Got questions, feedback or want to join a community of ML engineers working on exciting projects?

<a href="https://bit.ly/wb-slack"><img src="https://svgshare.com/i/M93.svg" alt="slack" width="55"/></a> Join our [slack](https://bit.ly/wb-slack) community.

[![Twitter](https://img.shields.io/twitter/follow/weights_biases?style=social)](https://twitter.com/weights_biases) Follow us on [Twitter](https://twitter.com/weights_biases).
