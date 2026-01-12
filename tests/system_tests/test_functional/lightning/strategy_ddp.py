from __future__ import annotations

import lightning as pl
from base import BoringModel, RandomDataset  # type: ignore
from lightning.pytorch.loggers import WandbLogger
from torch.utils.data import DataLoader


def main():
    # Set up data
    num_samples = 100000
    train = RandomDataset(32, num_samples)
    train = DataLoader(train, batch_size=32)
    val = RandomDataset(32, num_samples)
    val = DataLoader(val, batch_size=32)
    test = RandomDataset(32, num_samples)
    test = DataLoader(test, batch_size=32)
    # init model
    model = BoringModel()

    # set up wandb
    config = dict(some_hparam="Logged Before Trainer starts DDP")
    wandb_logger = WandbLogger(log_model=True, config=config, save_code=True)

    # Initialize a trainer
    trainer = pl.Trainer(
        max_epochs=1,
        devices=2,
        num_nodes=1,
        accelerator="cpu",
        strategy="ddp",
        logger=wandb_logger,
    )

    # Train the model
    trainer.fit(model, train, val)
    trainer.test(dataloaders=test)

    wandb_logger.experiment.finish()


if __name__ == "__main__":
    main()
