#!/usr/bin/env python
"""Test pytorch_lightning integration
WandbLogger tests in the Pytorch Lighning repo can be found here: 
https://github.com/PyTorchLightning/pytorch-lightning/blob/master/tests/loggers/test_wandb.py 

---
id: 0.0.4
check-ext-wandb: {}
assert:
  - :wandb:runs_len: 3
  - :wandb:runs[0][config][project]: integrations_testing
  - :wandb:runs[0][summary][acc]: 1.0
  - :wandb:runs[0][exitcode]: 0
  - :wandb:runs[1][config][test]: 123
  - :wandb:runs[1][exitcode]: 0
  - :wandb:runs[2][exitcode]: 0
"""

import torch
import wandb
import torch.nn as nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset

import pytorch_lightning as pl
from pytorch_lightning import LightningDataModule, LightningModule
from pytorch_lightning.loggers import WandbLogger


class RandomDataset(Dataset):
    def __init__(self, data_len: int = 100, bs: int = 8, h: int = 28, w: int = 28):
        self.data_len = data_len
        self.bs = bs
        self.h = h
        self.w = w

    def __len__(self):
        return self.data_len

    def __getitem__(self, idx):
        return (torch.rand(1, self.h, self.w), 5)


class RandomDataModule(LightningDataModule):
    def __init__(self, l: int = 100, bs: int = 8, h: int = 28, w: int = 28):
        super().__init__()

    def setup(self, stage: str = None):
        self.dataset = RandomDataset()

    # return the dataloader for each split
    def train_dataloader(self):
        return DataLoader(self.dataset)

    def val_dataloader(self):
        return DataLoader(self.dataset)


class LitAutoEncoder(LightningModule):
    def __init__(self):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(28 * 28, 64), nn.ReLU(), nn.Linear(64, 3)
        )
        self.decoder = nn.Sequential(
            nn.Linear(3, 64), nn.ReLU(), nn.Linear(64, 28 * 28)
        )

    def forward(self, x):
        embedding = self.encoder(x)
        return embedding

    def backward(self, loss, optimizer, optimizer_idx):
        loss.backward()

    def training_step(self, batch, batch_idx):
        x, y = batch
        x = x.view(x.size(0), -1)
        z = self.encoder(x)
        x_hat = self.decoder(z)
        loss = F.mse_loss(x_hat, x)
        self.log("train_loss", loss)
        return loss

    def validation_step(self, batch, batch_idx):
        x, y = batch
        x = x.view(x.size(0), -1)
        z = self.encoder(x)
        x_hat = self.decoder(z)
        loss = F.mse_loss(x_hat, x)
        self.log("validation_loss", loss + 0.1)
        return loss

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=1e-3)
        return optimizer


n_epoch = 3
project = "integrations_testing"

# Test WandbLogger logs metrics
wandb_logger = WandbLogger(project=project)
wandb_logger.log_metrics({"acc": 1.0})
wandb.finish()

# Test WandbLogger logs hyperparameters to wandb.config
wandb_logger = WandbLogger(project=project)
wandb_logger.log_hyperparams({"test": 123})
wandb.finish()

# Test training runs to completion with WandbLogger
autoencoder = LitAutoEncoder()
rand_data = RandomDataModule()
wandb_logger = WandbLogger(project=project)

trainer = pl.Trainer(
    logger=wandb_logger, log_every_n_steps=1, val_check_interval=0.5, max_epochs=n_epoch
)
trainer.fit(autoencoder, rand_data)
wandb.finish()
