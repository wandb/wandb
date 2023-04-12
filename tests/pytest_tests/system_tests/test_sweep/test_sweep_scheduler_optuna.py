import time
from unittest.mock import Mock

import optuna
import pytest
import wandb
from wandb.apis import internal, public
from wandb.sdk.launch.sweeps import SchedulerError
from wandb.sdk.launch.sweeps.scheduler_optuna import (
    OptunaScheduler,
    validate_optuna_pruner,
    validate_optuna_sampler,
)

from .test_wandb_sweep import VALID_SWEEP_CONFIGS_MINIMAL

OPTUNA_PRUNER_ARGS = {
    "PatientPruner": {
        "wrapped_pruner": Mock(),
        "patience": 1,
    },
    "PercentilePruner": {
        "percentile": 0.5,
    },
    "ThresholdPruner": {
        "lower": 0.5,
    },
}
OPTUNA_SAMPLER_ARGS = {
    "PartialFixedSampler": {
        "fixed_params": Mock(),
        "base_sampler": Mock(),
    },
    "GridSampler": {
        "search_space": {"x": [Mock()]},
    },
}


@pytest.mark.parametrize("pruner", optuna.pruners.__all__[1:])
def test_optuna_pruner_validation(pruner):
    config = {"type": pruner}
    if pruner in OPTUNA_PRUNER_ARGS:
        config["args"] = OPTUNA_PRUNER_ARGS[pruner]
    assert validate_optuna_pruner(config)


@pytest.mark.parametrize("sampler", optuna.samplers.__all__[1:-2])
def test_optuna_sampler_validation(sampler):
    config = {"type": sampler}
    if sampler in OPTUNA_SAMPLER_ARGS:
        config["args"] = OPTUNA_SAMPLER_ARGS[sampler]
    assert validate_optuna_sampler(config)


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
def test_optuna_scheduler_attrs(user, sweep_config, monkeypatch):
    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._try_load_executable",
        lambda _: True,
    )

    api = internal.Api()

    # def mock_upsert_run(self, **kwargs):
    #     return [Mock(spec=public.Run)]

    # api.upsert_run = mock_upsert_run

    project = "test-project"
    sweep_id = wandb.sweep(sweep_config, entity=user, project=project)

    scheduler = OptunaScheduler(
        api,
        sweep_type="optuna",
        sweep_id=sweep_id,
        entity=user,
        project=project,
        polling_sleep=0,
        num_workers=1,
    )

    assert scheduler.study_name == f"optuna-study-{sweep_id}"

    scheduler._study = Mock(spec=optuna.study.Study)

    assert scheduler.study
    assert scheduler.formatted_trials == {}

    config, trial = scheduler._make_trial()
    assert "parameters" in config

    srun = scheduler._get_next_sweep_run(0)
    assert srun

    assert scheduler._optuna_runs[srun.id].sweep_run == srun
    assert scheduler._optuna_runs[srun.id].num_metrics == 0
    assert scheduler._optuna_runs[srun.id].trial


def test_pythonic_search_space(user, monkeypatch):
    project = "test-project"
    api = internal.Api()
    api.sweep = Mock(
        spec=public.Sweep,
        side_effect=[{"config": {"parameters": {"x": {"value": 1}}}} * 2],
    )
    scheduler = OptunaScheduler(
        api,
        sweep_id="xxxxxxxx",
        entity=user,
        project=project,
        polling_sleep=0,
    )
    scheduler._study = Mock(spec=optuna.study.Study)

    def objective(trial):
        trial.suggest_uniform("x", -10, 10)
        trial.suggest_categorical("y", ["a", "b", "c"])
        return -1

    scheduler._objective_func = objective
    config, trial = scheduler._make_trial_from_objective()

    assert config["x"]["value"] in range(-10, 10)
    assert config["y"]["value"] in ["a", "b", "c"]
    assert trial.params["x"] in range(-10, 10)
    assert trial.params["y"] in ["a", "b", "c"]

    def objective(_trial):
        time.sleep(3)
        return -1

    scheduler._objective_func = objective
    with pytest.raises(SchedulerError):
        # timeout is 2 seconds
        scheduler._make_trial_from_objective()
