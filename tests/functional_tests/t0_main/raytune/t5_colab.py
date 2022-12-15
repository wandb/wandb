"""ray-tune test.

Based on:
    https://docs.wandb.ai/guides/integrations/other/ray-tune
    https://colab.research.google.com/github/wandb/examples/blob/master/colabs/raytune/RayTune_with_wandb.ipynb
"""

import random

import numpy as np
import torch
import torch.optim as optim
import wandb
from ray import tune
from ray.tune.examples.mnist_pytorch import ConvNet, get_data_loaders, test, train
from ray.tune.integration.wandb import WandbLogger, wandb_mixin


@wandb_mixin
def train_mnist(config):

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_loader, test_loader = get_data_loaders()

    model = ConvNet()
    model.to(device)

    optimizer = optim.SGD(
        model.parameters(), lr=config["lr"], momentum=config["momentum"]
    )

    for _i in range(10):
        train(model, optimizer, train_loader, device=device)
        acc = test(model, test_loader, device=device)

        # When using WandbLogger, the metrics reported to tune are also logged in the W&B dashboard
        tune.report(mean_accuracy=acc)

        # @wandb_mixin enables logging custom metrics using wandb.log()
        error_rate = 100 * (1 - acc)
        wandb.log({"error_rate": error_rate})


def run():
    torch.backends.cudnn.deterministic = True
    random.seed(2022)
    np.random.seed(2022)
    torch.manual_seed(2022)
    torch.cuda.manual_seed_all(2022)
    wandb.login()

    wandb_init = {"project": "raytune-colab"}

    analysis = tune.run(
        train_mnist,
        loggers=[WandbLogger],
        resources_per_trial={"gpu": 0},
        config={
            # wandb dict accepts all arguments that can be passed in wandb.init()
            "wandb": wandb_init,
            # hyperparameters are set by keyword arguments
            "lr": tune.grid_search([0.0001, 0.001, 0.1]),
            "momentum": tune.grid_search([0.9, 0.99]),
        },
    )

    print("Best config: ", analysis.get_best_config(metric="mean_accuracy", mode="max"))


if __name__ == "__main__":
    run()
