import wandb


def test_logger(dryrun):
    logger = wandb.ray.WandbLogger({"env_config": {"wandb": {"project": "test", "config": {"foo": 2, "bar": 3}}}}, ".")
    logger.on_result({"config": {"foo": 1}, "metric": 1, "garbage": "two"})
    logger.close()
    assert wandb.run.summary["metric"] == 1
    assert wandb.run.summary.get("garbage") is None
    assert wandb.config.foo == 2
    assert wandb.config.bar == 3
    assert wandb.run.project_name() == "test"
