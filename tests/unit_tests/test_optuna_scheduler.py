from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import optuna
import pytest
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.optimizer import (
    RunConfig,
    RunSuggestion,
    RunWithMetrics,
)
from wandb.sdk.sweeps.scheduler.optuna import (
    OptunaDeclarativeOptimizer,
    OptunaImperativeOptimizer,
    OptunaOptions,
    create_study_from_sweep_config,
    make_optimizer,
)
from wandb.sdk.sweeps.sweep_info import SweepInfo

from tests.unit_tests.test_sweep_scheduler import make_scheduler_grid_sweep

optuna.logging.set_verbosity(optuna.logging.WARNING)


DEFAULT_CONFIG = {"metric": {"name": "loss", "goal": "minimize"}, "parameters": {}}


@pytest.fixture
def sweep() -> SweepInfo:
    return make_scheduler_grid_sweep(config=DEFAULT_CONFIG)


@pytest.fixture
def study() -> optuna.Study:
    return optuna.create_study(direction="minimize")


class TestMakeOptimizer:
    """The flavor `wandb sweep-scheduler` gets for a set of options."""

    def test_builds_declarative_optimizer(
        self, study: optuna.Study, sweep: SweepInfo
    ) -> None:
        distributions = {"x": optuna.distributions.FloatDistribution(0.0, 1.0)}

        optimizer = make_optimizer(
            study,
            sweep,
            OptunaOptions(study=study, distributions=distributions),
        )

        assert isinstance(optimizer, OptunaDeclarativeOptimizer)
        assert optimizer.study is study
        assert optimizer.distributions is distributions
        assert optimizer._sweep is sweep

    def test_builds_imperative_optimizer(
        self, study: optuna.Study, sweep: SweepInfo
    ) -> None:
        def trial_constructor(trial: optuna.Trial) -> dict[str, Any]:
            return {"x": trial.suggest_float("x", 0.0, 1.0)}

        optimizer = make_optimizer(
            study,
            sweep,
            OptunaOptions(study=study, search_space=trial_constructor),
        )

        assert isinstance(optimizer, OptunaImperativeOptimizer)
        assert optimizer.trial_constructor is trial_constructor

    @pytest.mark.parametrize(
        "extra",
        [
            {},
            {"distributions": {}, "search_space": lambda trial: {}},
        ],
        ids=["neither", "both"],
    )
    def test_requires_exactly_one_of_distributions_or_search_space(
        self, study: optuna.Study, sweep: SweepInfo, extra: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            make_optimizer(study, sweep, OptunaOptions(study=study, **extra))

    def test_forwards_the_terminator_to_the_optimizer(
        self, study: optuna.Study, sweep: SweepInfo
    ) -> None:
        terminator = MagicMock()

        optimizer = make_optimizer(
            study,
            sweep,
            OptunaOptions(study=study, distributions={}, terminator=terminator),
        )

        assert optimizer._terminator is terminator


class TestCreateStudyFromSweepConfig:
    def test_creates_single_objective_study_from_metric(self) -> None:
        study = create_study_from_sweep_config(
            {"metric": {"name": "loss", "goal": "maximize"}}
        )

        assert study.direction == optuna.study.StudyDirection.MAXIMIZE

    def test_creates_multi_objective_study_from_metrics(self) -> None:
        study = create_study_from_sweep_config(
            {
                "metrics": [
                    {"name": "loss", "goal": "minimize"},
                    {"name": "accuracy", "goal": "maximize"},
                ]
            }
        )

        assert [d.name.lower() for d in study.directions] == ["minimize", "maximize"]


class TestBuildOptunaSchedulerOptimizer:
    def test_creates_multi_objective_study_from_metrics_config(self) -> None:
        from wandb.cli import cli

        config = {
            "metrics": [
                {"name": "loss", "goal": "minimize"},
                {"name": "accuracy", "goal": "maximize"},
            ],
            "parameters": {"lr": {"min": 0.0, "max": 1.0}},
            "scheduler": {"engine": "optuna"},
        }
        sweep = make_scheduler_grid_sweep(config=config)

        optimizer = cli._build_optuna_scheduler_optimizer(sweep, config["scheduler"])

        assert isinstance(optimizer, OptunaDeclarativeOptimizer)
        assert [d.name.lower() for d in optimizer.study.directions] == [
            "minimize",
            "maximize",
        ]

    def test_optimizer_config_returns_study(self, tmp_path) -> None:
        from wandb.cli import cli

        source = tmp_path / "optimizer.py"
        source.write_text(
            "import optuna\n\n"
            "def configure():\n"
            "    return optuna.create_study(direction='minimize')\n",
            encoding="utf-8",
        )
        config = {
            "metric": {"name": "loss", "goal": "minimize"},
            "parameters": {"lr": {"min": 0.0, "max": 1.0}},
            "scheduler": {
                "engine": "optuna",
                "source": str(source),
                "optimizer": "configure",
            },
        }
        sweep = make_scheduler_grid_sweep(config=config)

        optimizer = cli._build_optuna_scheduler_optimizer(sweep, config["scheduler"])

        assert isinstance(optimizer.study, optuna.Study)
        assert optimizer.should_terminate_sweep() is False

    def test_optimizer_config_returns_study_and_terminator(self, tmp_path) -> None:
        from wandb.cli import cli

        source = tmp_path / "optimizer.py"
        source.write_text(
            "import optuna\n\n"
            "def should_stop(study):\n"
            "    return True\n\n"
            "def configure():\n"
            "    study = optuna.create_study(direction='minimize')\n"
            "    return study, should_stop\n",
            encoding="utf-8",
        )
        config = {
            "metric": {"name": "loss", "goal": "minimize"},
            "parameters": {"lr": {"min": 0.0, "max": 1.0}},
            "scheduler": {
                "engine": "optuna",
                "source": str(source),
                "optimizer": "configure",
            },
        }
        sweep = make_scheduler_grid_sweep(config=config)

        optimizer = cli._build_optuna_scheduler_optimizer(sweep, config["scheduler"])

        assert optimizer.should_terminate_sweep() is True


class TestMultiObjective:
    """Multi-objective sweeps declare their objectives in `metrics`."""

    METRICS_CONFIG = {
        "metrics": [
            {"name": "loss", "goal": "minimize"},
            {"name": "accuracy", "goal": "maximize"},
        ],
        "parameters": {"x": {"min": 0.0, "max": 1.0}},
    }

    @pytest.fixture
    def optimizer(self) -> OptunaDeclarativeOptimizer:
        study = create_study_from_sweep_config(self.METRICS_CONFIG)
        sweep = make_scheduler_grid_sweep(config=self.METRICS_CONFIG)
        distributions = {"x": optuna.distributions.FloatDistribution(0.0, 1.0)}
        return OptunaDeclarativeOptimizer(study, distributions, sweep)

    def make_run(self, suggestion, summary, state=RunState.FINISHED):
        return RunWithMetrics(
            config=suggestion.config,
            state=state,
            wandb_run_id="wandb-run-id",
            summary_metrics=summary,
            history_metrics=[{"loss": 2.0, "accuracy": 0.5, "_step": 1}],
        )

    def test_tell_run_records_every_objective(self, optimizer) -> None:
        suggestion = next(iter(optimizer.ask_n_runs(1)))

        optimizer.tell_run(
            suggestion.run_id,
            self.make_run(suggestion, {"loss": 1.5, "accuracy": 0.75}),
        )

        trials = optimizer.study.get_trials(deepcopy=False)
        assert len(trials) == 1
        assert trials[0].state == optuna.trial.TrialState.COMPLETE
        assert trials[0].values == [1.5, 0.75]

    def test_tell_run_fails_a_run_missing_an_objective(self, optimizer) -> None:
        suggestion = next(iter(optimizer.ask_n_runs(1)))

        optimizer.tell_run(suggestion.run_id, self.make_run(suggestion, {"loss": 1.5}))

        trials = optimizer.study.get_trials(deepcopy=False)
        assert trials[0].state == optuna.trial.TrialState.FAIL

    def test_prune_run_is_never_pruned(self, optimizer) -> None:
        """optuna's pruners rank one value, so they cannot judge these."""
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        run = self.make_run(suggestion, {"loss": 9.0}, state=RunState.RUNNING)
        optimizer.tell_run(suggestion.run_id, run)

        assert optimizer.prune_runs([suggestion.run_id], [run]) == []

    def test_warm_start_records_every_objective(self, optimizer) -> None:
        existing = RunSuggestion(
            config=RunConfig.from_values({"x": 0.25}), run_id="prior"
        )

        optimizer.tell_existing_finished_run(
            self.make_run(existing, {"loss": 0.5, "accuracy": 0.9})
        )

        trials = optimizer.study.get_trials(deepcopy=False)
        assert len(trials) == 1
        assert trials[0].values == [0.5, 0.9]


class TestIntermediateReporting:
    """Single-objective sweeps report intermediate values for pruning."""

    @pytest.fixture
    def optimizer(self, sweep: SweepInfo) -> OptunaDeclarativeOptimizer:
        study = optuna.create_study(direction="minimize")
        distributions = {"x": optuna.distributions.FloatDistribution(0.0, 1.0)}
        return OptunaDeclarativeOptimizer(study, distributions, sweep)

    def test_tell_run_rejects_history_missing_step(self, optimizer) -> None:
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        run = RunWithMetrics(
            config=suggestion.config,
            state=RunState.RUNNING,
            wandb_run_id="wandb-run-id",
            summary_metrics={},
            history_metrics=[{"loss": 1.0}],
        )

        with pytest.raises(ValueError, match="_step"):
            optimizer.tell_run(suggestion.run_id, run)
