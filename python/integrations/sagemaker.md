# SageMaker

### SageMaker Integration

W&B integrates with [Amazon SageMaker](https://aws.amazon.com/sagemaker/), automatically reading hyperparameters, grouping distributed runs, and resuming runs from checkpoints.

#### Authentication

W&B looks for a file named `secrets.env` relative to the training script and loads them into the environment when `wandb.init()` is called. You can generate a `secrets.env` file by calling `wandb.sagemaker_auth(path="source_dir")` in the script you use to launch your experiments. Be sure to add this file to your `.gitignore`!

#### Existing Estimators

If you're using one of SageMakers preconfigured estimators you need to add a `requirements.txt` to your source directory that includes wandb

```text
wandb
```

If you're using an estimator that's running Python 2, you'll need to install psutil directly from a [wheel](https://wheels.galaxyproject.org/packages) before installing wandb:

```text
https://wheels.galaxyproject.org/packages/psutil-5.4.8-cp27-cp27mu-manylinux1_x86_64.whl
wandb
```

A complete example is available on [GitHub](https://github.com/wandb/examples/tree/master/pytorch-cifar10-sagemaker) and you can read more on our [blog](https://www.wandb.com/blog/running-sweeps-with-sagemaker).

