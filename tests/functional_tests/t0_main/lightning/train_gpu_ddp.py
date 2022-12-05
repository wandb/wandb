#!/usr/bin/env python

import os
import pathlib

import wandb
from pl_base import BoringModel, RandomDataset
from pytorch_lightning import Trainer
from pytorch_lightning.loggers import WandbLogger
from torch.utils.data import DataLoader


def main():
    # Use concurrency experiment
    wandb.require(experiment="service")

    # boost stats logging frequency for testing
    stats_settings = dict(_stats_sample_rate_seconds=0.5, _stats_samples_to_average=2)
    wandb.setup(settings=stats_settings)

    print("User process PID:", os.getpid())

    # Set up data
    num_samples = 100000
    train = DataLoader(RandomDataset(32, num_samples), batch_size=32)
    val = DataLoader(RandomDataset(32, num_samples), batch_size=32)
    test = DataLoader(RandomDataset(32, num_samples), batch_size=32)
    # init model
    model = BoringModel()

    # set up wandb
    config = dict(some_hparam="Logged Before Trainer starts DDP")
    wandb_logger = WandbLogger(
        log_model=True,
        config=config,
        save_code=True,
        name=pathlib.Path(__file__).stem,
    )

    # Initialize a trainer
    trainer = Trainer(
        max_epochs=2,
        devices=2,
        accelerator="gpu",
        strategy="ddp",
        logger=wandb_logger,
    )

    # Train the model
    trainer.fit(model, train, val)
    trainer.test(dataloaders=test)


if __name__ == "__main__":
    main()
