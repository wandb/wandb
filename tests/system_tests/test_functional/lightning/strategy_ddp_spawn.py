from base import BoringModel, RandomDataset  # type: ignore
from lightning import Trainer
from lightning.pytorch.loggers import WandbLogger
from torch.utils.data import DataLoader


def main():
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
        devices=2,
        accelerator="cpu",
        strategy="ddp_spawn",
        logger=wandb_logger,
    )

    # Train the model
    trainer.fit(model, train, val)
    trainer.test(dataloaders=test)

    wandb_logger.experiment.finish()


if __name__ == "__main__":
    main()
