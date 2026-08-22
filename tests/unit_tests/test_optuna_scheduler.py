from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

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
    create_sweep,
    create_sweep_from_config,
    resume_sweep,
)
from wandb.sdk.sweeps.sweep_info import SweepInfo

from tests.unit_tests.test_sweep_scheduler import make_scheduler_grid_sweep

optuna.logging.set_verbosity(optuna.logging.WARNING)


DEFAULT_CONFIG = {"metric": {"name": "loss", "goal": "minimize"}, "parameters": {}}

SWEEP_PATH = "test_entity/test_project/test_sweep"


@pytest.fixture
def sweep() -> SweepInfo:
    return make_scheduler_grid_sweep(config=DEFAULT_CONFIG)


@pytest.fixture
def study() -> optuna.Study:
    return optuna.create_study(direction="minimize")


@pytest.fixture
def run_scheduler_mock():
    """The entry points hand an optimizer factory to `run_scheduler`."""
    with patch("wandb.sdk.sweeps.scheduler.optuna.run_scheduler") as run_scheduler:
        yield run_scheduler


@pytest.fixture
def wandb_sweep_mock():
    """The create-sweep entry points create the sweep through `wandb_sweep`."""
    with patch(
        "wandb.sdk.sweeps.scheduler.optuna.wandb_sweep",
        return_value="test_sweep",
    ) as wandb_sweep:
        yield wandb_sweep


def built_optimizer(run_scheduler_mock: MagicMock, sweep: SweepInfo) -> Any:
    """Build the optimizer the captured factory produces for `sweep`."""
    return run_scheduler_mock.call_args.kwargs["make_optimizer"](sweep)


class TestResumeSweep:
    def test_builds_declarative_optimizer(
        self, run_scheduler_mock: MagicMock, study: optuna.Study, sweep: SweepInfo
    ) -> None:
        distributions = {"x": optuna.distributions.FloatDistribution(0.0, 1.0)}

        resume_sweep(
            SWEEP_PATH,
            options=OptunaOptions(study=study, distributions=distributions),
        )

        kwargs = run_scheduler_mock.call_args.kwargs
        assert kwargs["entity"] == "test_entity"
        assert kwargs["project"] == "test_project"
        assert kwargs["sweep_id"] == "test_sweep"
        # No poll/batch given: defaults from `OptunaOptions()`.
        assert kwargs["poll_interval"] == OptunaOptions().poll_interval_s
        assert kwargs["batch_size"] == OptunaOptions().batch_size

        optimizer = built_optimizer(run_scheduler_mock, sweep)
        assert isinstance(optimizer, OptunaDeclarativeOptimizer)
        assert optimizer.study is study
        assert optimizer.distributions is distributions
        assert optimizer._sweep is sweep

    def test_builds_imperative_optimizer(
        self, run_scheduler_mock: MagicMock, study: optuna.Study, sweep: SweepInfo
    ) -> None:
        def trial_constructor(trial: optuna.Trial) -> dict[str, Any]:
            return {"x": trial.suggest_float("x", 0.0, 1.0)}

        resume_sweep(
            SWEEP_PATH,
            options=OptunaOptions(study=study, search_space=trial_constructor),
        )

        optimizer = built_optimizer(run_scheduler_mock, sweep)
        assert isinstance(optimizer, OptunaImperativeOptimizer)
        assert optimizer.trial_constructor is trial_constructor

    def test_uses_given_scheduler_options(
        self, run_scheduler_mock: MagicMock, study: optuna.Study
    ) -> None:
        resume_sweep(
            SWEEP_PATH,
            options=OptunaOptions(
                study=study,
                distributions={},
                poll_interval_s=1.5,
                batch_size=3,
            ),
        )

        kwargs = run_scheduler_mock.call_args.kwargs
        assert kwargs["poll_interval"] == 1.5
        assert kwargs["batch_size"] == 3

    def test_requires_a_full_sweep_path(self, study: optuna.Study) -> None:
        with pytest.raises(ValueError, match="entity/project/sweep_id"):
            resume_sweep(
                "bare-id",
                options=OptunaOptions(study=study, distributions={}),
            )

    def test_requires_a_study(self) -> None:
        with pytest.raises(ValueError, match="study"):
            resume_sweep(SWEEP_PATH, options=OptunaOptions(distributions={}))

    @pytest.mark.parametrize(
        "extra",
        [
            {},
            {"distributions": {}, "search_space": lambda trial: {}},
        ],
        ids=["neither", "both"],
    )
    def test_requires_exactly_one_of_distributions_or_search_space(
        self,
        run_scheduler_mock: MagicMock,
        study: optuna.Study,
        sweep: SweepInfo,
        extra: dict[str, Any],
    ) -> None:
        resume_sweep(SWEEP_PATH, options=OptunaOptions(study=study, **extra))

        with pytest.raises(ValueError, match="exactly one"):
            built_optimizer(run_scheduler_mock, sweep)

    def test_forwards_the_terminator_to_the_optimizer(
        self, run_scheduler_mock: MagicMock, study: optuna.Study, sweep: SweepInfo
    ) -> None:
        terminator = MagicMock()

        resume_sweep(
            SWEEP_PATH,
            options=OptunaOptions(study=study, distributions={}, terminator=terminator),
        )

        assert built_optimizer(run_scheduler_mock, sweep)._terminator is terminator


class TestCreateSweep:
    def test_declarative_path_builds_sweep_and_delegates(
        self,
        run_scheduler_mock: MagicMock,
        wandb_sweep_mock: MagicMock,
        study: optuna.Study,
        sweep: SweepInfo,
    ) -> None:
        distributions = {"lr": optuna.distributions.FloatDistribution(0.0, 1.0)}

        create_sweep(
            "test_entity",
            "test_project",
            "loss",
            program_path="train.py",
            options=OptunaOptions(study=study, distributions=distributions),
        )

        wandb_sweep_mock.assert_called_once_with(
            {
                "metric": {"name": "loss", "goal": "minimize"},
                "parameters": {
                    "lr": {"distribution": "uniform", "min": 0.0, "max": 1.0}
                },
                "scheduler": {"engine": "optuna"},
                "program": "train.py",
            },
            entity="test_entity",
            project="test_project",
        )
        assert run_scheduler_mock.call_args.kwargs["sweep_id"] == "test_sweep"
        optimizer = built_optimizer(run_scheduler_mock, sweep)
        assert isinstance(optimizer, OptunaDeclarativeOptimizer)
        assert optimizer.distributions is distributions

    def test_imperative_path_discovers_space_and_keeps_the_constructor(
        self,
        run_scheduler_mock: MagicMock,
        wandb_sweep_mock: MagicMock,
        study: optuna.Study,
        sweep: SweepInfo,
    ) -> None:
        """Regression test: the discovered space must not overwrite the
        constructor the imperative optimizer needs -- `create_sweep` used to
        shadow its `search_space` parameter with the discovered
        distributions dict before forwarding it, silently swapping the
        callable for a dict.
        """

        def trial_constructor(trial: optuna.Trial) -> dict[str, Any]:
            return {"lr": trial.suggest_float("lr", 0.0, 1.0)}

        create_sweep(
            "test_entity",
            "test_project",
            "loss",
            options=OptunaOptions(study=study, search_space=trial_constructor),
        )

        # The space `_spy_search_space` discovered by really running
        # `trial_constructor` made it into the sweep the server was asked to
        # create.
        sent_config = wandb_sweep_mock.call_args[0][0]
        assert sent_config["parameters"] == {
            "lr": {"distribution": "uniform", "min": 0.0, "max": 1.0}
        }
        # But the optimizer that drives the rest of the sweep keeps the
        # original callable, not that discovered dict.
        optimizer = built_optimizer(run_scheduler_mock, sweep)
        assert isinstance(optimizer, OptunaImperativeOptimizer)
        assert optimizer.trial_constructor is trial_constructor

    def test_requires_a_study(self) -> None:
        with pytest.raises(ValueError, match="study"):
            create_sweep(
                "test_entity",
                "test_project",
                "loss",
                options=OptunaOptions(distributions={}),
            )

    @pytest.mark.parametrize(
        "extra",
        [
            {},
            {"distributions": {}, "search_space": lambda trial: {}},
        ],
        ids=["neither", "both"],
    )
    def test_requires_exactly_one_of_distributions_or_search_space(
        self, study: optuna.Study, extra: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            create_sweep(
                "test_entity",
                "test_project",
                "loss",
                options=OptunaOptions(study=study, **extra),
            )


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


class TestCreateSweepFromConfig:
    CONFIG = {
        "metric": {"name": "loss", "goal": "minimize"},
        "parameters": {"lr": {"min": 0.0, "max": 1.0}},
    }

    def test_builds_sweep_and_declarative_optimizer_from_config(
        self,
        run_scheduler_mock: MagicMock,
        wandb_sweep_mock: MagicMock,
        study: optuna.Study,
        sweep: SweepInfo,
    ) -> None:
        create_sweep_from_config(
            self.CONFIG,
            "test_entity",
            "test_project",
            options=OptunaOptions(study=study),
        )

        wandb_sweep_mock.assert_called_once_with(
            {**self.CONFIG, "scheduler": {"engine": "optuna"}},
            entity="test_entity",
            project="test_project",
        )
        kwargs = run_scheduler_mock.call_args.kwargs
        assert kwargs["sweep_id"] == "test_sweep"
        assert kwargs["poll_interval"] == OptunaOptions().poll_interval_s
        assert kwargs["batch_size"] == OptunaOptions().batch_size

        optimizer = built_optimizer(run_scheduler_mock, sweep)
        assert isinstance(optimizer, OptunaDeclarativeOptimizer)
        assert optimizer.study is study
        assert optimizer.distributions == {
            "lr": optuna.distributions.FloatDistribution(0.0, 1.0)
        }

    def test_creates_a_study_from_the_configs_goal_when_none_given(
        self, run_scheduler_mock: MagicMock, wandb_sweep_mock: MagicMock
    ) -> None:
        maximize_config = {
            "metric": {"name": "loss", "goal": "maximize"},
            "parameters": {},
        }

        create_sweep_from_config(maximize_config, "test_entity", "test_project")

        optimizer = built_optimizer(
            run_scheduler_mock, make_scheduler_grid_sweep(config=maximize_config)
        )
        assert optimizer.study.direction == optuna.study.StudyDirection.MAXIMIZE

    def test_uses_given_scheduler_options(
        self,
        run_scheduler_mock: MagicMock,
        wandb_sweep_mock: MagicMock,
        study: optuna.Study,
    ) -> None:
        create_sweep_from_config(
            self.CONFIG,
            "test_entity",
            "test_project",
            options=OptunaOptions(
                study=study,
                poll_interval_s=2.5,
                batch_size=7,
            ),
        )

        kwargs = run_scheduler_mock.call_args.kwargs
        assert kwargs["poll_interval"] == 2.5
        assert kwargs["batch_size"] == 7

    def test_forwards_the_terminator_to_the_optimizer(
        self,
        run_scheduler_mock: MagicMock,
        wandb_sweep_mock: MagicMock,
        study: optuna.Study,
        sweep: SweepInfo,
    ) -> None:
        terminator = MagicMock()

        create_sweep_from_config(
            self.CONFIG,
            "test_entity",
            "test_project",
            options=OptunaOptions(study=study, terminator=terminator),
        )

        assert built_optimizer(run_scheduler_mock, sweep)._terminator is terminator

    def test_rejects_another_engine(self, study: optuna.Study) -> None:
        with pytest.raises(ValueError, match="ax"):
            create_sweep_from_config(
                {"scheduler": {"engine": "ax"}, "parameters": {}},
                "test_entity",
                "test_project",
                options=OptunaOptions(study=study),
            )


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
