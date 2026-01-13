from ray import tune
from ray.air.integrations.wandb import WandbLoggerCallback


def train_fc(config):
    for i in range(10):
        tune.report({"mean_accuracy": (i + config["alpha"]) / 10})


search_space = {
    "alpha": tune.grid_search([0.1, 0.2, 0.3]),
    "beta": tune.uniform(0.5, 1.0),
}

analysis = tune.run(
    train_fc,
    config=search_space,
    callbacks=[
        WandbLoggerCallback(
            project="raytune",
            log_config=True,
        )
    ],
)

best_trial = analysis.get_best_trial("mean_accuracy", "max", "last")
