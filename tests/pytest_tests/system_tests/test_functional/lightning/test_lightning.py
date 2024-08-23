import pytest
from base import BoringModel, RandomDataset
from lightning import Trainer
from lightning.pytorch.loggers import WandbLogger
from torch.utils.data import DataLoader


@pytest.mark.wandb_core_only
@pytest.mark.parametrize("strategy", ["ddp_spawn"])
def test_strategy_ddp_spawn(user, relay_server, strategy):
    with relay_server() as relay:
        # Set up data
        num_samples = 100000
        train = DataLoader(RandomDataset(32, num_samples), batch_size=32)
        val = DataLoader(RandomDataset(32, num_samples), batch_size=32)
        test = DataLoader(RandomDataset(32, num_samples), batch_size=32)
        # init model
        model = BoringModel()

        # set up wandb logger
        config = dict(some_hparam="Logged Before Trainer starts DDP")
        wandb_logger = WandbLogger(log_model=True, config=config, save_code=True)

        # Initialize a trainer
        trainer = Trainer(
            max_epochs=1,
            devices=2,
            accelerator="cpu",
            strategy=strategy,
            logger=wandb_logger,
        )

        # Train the model
        trainer.fit(model, train, val)
        trainer.test(dataloaders=test)

        wandb_logger.experiment.finish()

    # assertions
    run_id = wandb_logger.experiment.id
    assert len(relay.context.get_run_ids()) == 1
    history = relay.context.get_run_history(run_id)
    assert history["trainer/global_step"][30] == 1549
    config = relay.context.get_run_config(run_id)
    assert config["some_hparam"]["value"] == "Logged Before Trainer starts DDP"
    summary = relay.context.get_run_summary(run_id)
    assert summary["epoch"] == 0
    assert summary["loss"] >= 0
    assert summary["trainer/global_step"] == 0
    assert summary["fake_test_acc"] >= 0
    telemetry = relay.context.get_run_telemetry(run_id)
    assert 106 in telemetry["2"]  # import=lightning
