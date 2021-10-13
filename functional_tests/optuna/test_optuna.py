import optuna
import wandb
from optuna.integration.wandb import WeightsAndBiasesCallback


def objective(trial):
    x = trial.suggest_float("x", -10, 10)
    return (x - 2) ** 2


n_trials = 5
wandb_kwargs = {"project": "integrations_testing", "config": {"a": 2, "b": "testing"}}
wandbc = WeightsAndBiasesCallback(wandb_kwargs=wandb_kwargs)
study = optuna.create_study(study_name="my_study")
study.optimize(objective, n_trials=n_trials, callbacks=[wandbc])
wandb.finish()
