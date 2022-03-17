#!/usr/bin/env python

import os

from pl_base import BoringModel, RandomDataset
import pytorch_lightning as pl
from pytorch_lightning.loggers import WandbLogger
from torch.utils.data import DataLoader, Dataset


# class RandomDataset(Dataset):
#     def __init__(self, size, num_samples):
#         self.len = num_samples
#         self.data = torch.randn(num_samples, size)

#     def __getitem__(self, index):
#         return self.data[index]

#     def __len__(self):
#         return self.len


# class BoringModel(LightningModule):
#     def __init__(self, value=1):
#         super().__init__()
#         # currently, will create 2 runs without calling `save_hyperparameters`.
#         # TODO remove this once we resolve the issue with PL
#         self.save_hyperparameters()
#         self.layer = torch.nn.Linear(32, 2)

#     def forward(self, x):
#         return self.layer(x)

#     def loss(self, batch, prediction):
#         # An arbitrary loss to have a loss that updates the model weights during `Trainer.fit` calls
#         return torch.nn.functional.mse_loss(prediction, torch.ones_like(prediction))

#     def training_step(self, batch, batch_idx):
#         output = self.layer(batch)
#         loss = self.loss(batch, output)
#         self.log("loss", loss)
#         return {"loss": loss}

#     def training_step_end(self, training_step_outputs):
#         return training_step_outputs

#     def training_epoch_end(self, outputs) -> None:
#         torch.stack([x["loss"] for x in outputs]).mean()

#     def validation_step(self, batch, batch_idx):
#         output = self.layer(batch)
#         loss = self.loss(batch, output)
#         return {"x": loss}

#     def validation_epoch_end(self, outputs) -> None:
#         torch.stack([x["x"] for x in outputs]).mean()

#     def test_step(self, batch, batch_idx):
#         output = self.layer(batch)
#         loss = self.loss(batch, output)
#         self.log("fake_test_acc", loss)
#         return {"y": loss}

#     def test_epoch_end(self, outputs) -> None:
#         torch.stack([x["y"] for x in outputs]).mean()

#     def configure_optimizers(self):
#         optimizer = torch.optim.SGD(self.layer.parameters(), lr=0.1)
#         lr_scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=1)
#         return [optimizer], [lr_scheduler]


def main():
    # Use concurrency experiment
    print("PIDPID", os.getpid())

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
        progress_bar_refresh_rate=20,
        num_processes=2,
        accelerator="ddp",
        logger=wandb_logger,
    )

    # Train the model
    trainer.fit(model, train, val)
    trainer.test(dataloaders=test)


if __name__ == "__main__":
    main()
