#!/usr/bin/env python

import os

import wandb
from pl_base import BoringModel, RandomDataset
from pytorch_lightning import Trainer
from pytorch_lightning.loggers import WandbLogger
from torch.utils.data import DataLoader


def main():
    # Use concurrency experiment
    wandb.require(experiment="service")
    print("PIDPID", os.getpid())

    # Set up data
    num_samples = 100000
    train = DataLoader(RandomDataset(32, num_samples), batch_size=32)
    val = DataLoader(RandomDataset(32, num_samples), batch_size=32)
    test = DataLoader(RandomDataset(32, num_samples), batch_size=32)
    # init model
    model = BoringModel()

    # set up wandb
    config = dict(some_hparam="Logged Before Trainer starts DDP")
    wandb_logger = WandbLogger(log_model=True, config=config, save_code=True)

    # Initialize a trainer
    trainer = Trainer(
        max_epochs=1,
        logger=wandb_logger,
        accelerator="tpu",
        devices=8,
        strategy="ddp",
    )

    # Train the model
    trainer.fit(model, train, val)
    trainer.test(test_dataloaders=test)


if __name__ == "__main__":
    # export TPU_IP_ADDRESS=your-tpu-ip-address
    # export XRT_TPU_CONFIG="tpu_worker;0;$TPU_IP_ADDRESS:8470"

    main()
