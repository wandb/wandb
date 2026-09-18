from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import optuna
import pytest
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.optimizer import Run, RunConfig, RunWithMetrics
from wandb.sdk.sweeps.scheduler.optuna import (
    OptunaDeclarativeOptimizer,
    OptunaImperativeOptimizer,
    OptunaOptions,
    create_study_from_sweep_config,
    make_optimizer,
    sweep_parameter_to_distribution,
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


class TestQDefault:
    """A missing `q` is 1 for both stepped distributions."""

    @pytest.mark.parametrize(
        ("parameter", "expected"),
        [
            (
                {"distribution": "q_uniform", "min": 0, "max": 10},
                optuna.distributions.IntDistribution(0, 10, step=1),
            ),
            (
                {"distribution": "q_log_uniform_values", "min": 1, "max": 1000},
                optuna.distributions.IntDistribution(1, 1000, log=True, step=1),
            ),
        ],
        ids=["q_uniform", "q_log_uniform_values"],
    )
    def test_defaults_q_to_one(
        self,
        parameter: dict[str, Any],
        expected: optuna.distributions.BaseDistribution,
    ) -> None:
        assert sweep_parameter_to_distribution(parameter) == expected


class TestQLogUniformValues:
    """optuna's log-scale int space only accepts `step=1` and `min >= 1`."""

    @pytest.mark.parametrize(
        "parameter",
        [
            {"min": 1e-4, "max": 1e-1, "q": 1e-5},
            {"min": 1e-4, "max": 1e-1},
            {"min": 10, "max": 1000, "q": 5},
        ],
        ids=["min_below_one_and_q", "min_below_one", "q_not_one"],
    )
    def test_falls_back_to_log_float_distribution(
        self, parameter: dict[str, Any], mock_wandb_log
    ) -> None:
        distribution = sweep_parameter_to_distribution(
            {"distribution": "q_log_uniform_values", **parameter}
        )

        assert distribution == optuna.distributions.FloatDistribution(
            parameter["min"], parameter["max"], log=True
        )
        mock_wandb_log.assert_warned("Converting to a FloatDistribution(log=True)")


class TestCreateStudyFromSweepConfig:
    @pytest.mark.parametrize(
        ("objective", "directions"),
        [
            ({"metric": {"name": "loss", "goal": "maximize"}}, ["maximize"]),
            (
                {
                    "metrics": [
                        {"name": "loss", "goal": "minimize"},
                        {"name": "accuracy", "goal": "maximize"},
                    ]
                },
                ["minimize", "maximize"],
            ),
        ],
        ids=["metric", "metrics"],
    )
    def test_creates_a_direction_per_declared_objective(
        self, objective: dict[str, Any], directions: list[str]
    ) -> None:
        study = create_study_from_sweep_config(objective)

        assert [d.name.lower() for d in study.directions] == directions

    def test_the_study_never_prunes(self) -> None:
        study = create_study_from_sweep_config({"metric": {"name": "loss"}})

        assert isinstance(study.pruner, optuna.pruners.NopPruner)


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


class TestExhaustibleSampler:
    """A finite sampler must finish the sweep instead of re-running the grid.

    optuna's GridSampler stops the study from `after_trial` once the grid is
    spent, and hands out duplicate grid points rather than refusing an ask.

    `OptunaOptimizerAcceptanceTests` cannot host these: its sampler never
    reports exhaustion, and the `Optimizer` contract does not require one to,
    so this builds its own GridSampler study rather than reusing that suite's
    `study` fixture.
    """

    CONFIG = {
        "metric": {"name": "loss", "goal": "minimize"},
        "parameters": {"x": {"values": [1, 2]}},
    }
    DISTRIBUTIONS = {"x": optuna.distributions.CategoricalDistribution([1, 2])}

    @pytest.fixture
    def optimizer(self) -> OptunaDeclarativeOptimizer:
        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.GridSampler({"x": [1, 2]}),
        )
        sweep = make_scheduler_grid_sweep(config=self.CONFIG)
        return OptunaDeclarativeOptimizer(study, self.DISTRIBUTIONS, sweep)

    def finish(self, optimizer: OptunaDeclarativeOptimizer, suggestion) -> None:
        optimizer.tell_run(
            suggestion.run_id,
            RunWithMetrics(
                config=suggestion.config,
                state=RunState.FINISHED,
                wandb_run_id="wandb-run-id",
                summary_metrics={"loss": 0.5},
                history_metrics=[{"loss": 0.5, "_step": 1}],
            ),
        )

    def test_the_spent_grid_records_its_trials_then_asks_for_nothing(
        self, optimizer
    ) -> None:
        """The sampler's stop request must not fail the run's tell."""
        for suggestion in optimizer.ask_n_runs(2):
            self.finish(optimizer, suggestion)

        trials = optimizer.study.get_trials(deepcopy=False)
        assert [trial.state for trial in trials] == [
            optuna.trial.TrialState.COMPLETE
        ] * 2
        assert optimizer.ask_n_runs(2) == []

    def test_ask_still_suggests_while_the_grid_is_in_flight(self, optimizer) -> None:
        """An empty batch finishes the sweep, so pending trials must not."""
        optimizer.ask_n_runs(2)

        assert optimizer.ask_n_runs(1) != []

    def test_adopts_an_active_run_after_exhaustion(self, optimizer) -> None:
        """Enqueued params are fixed, so they cost the spent grid nothing."""
        for suggestion in optimizer.ask_n_runs(2):
            self.finish(optimizer, suggestion)

        run_id = optimizer.tell_existing_active_run(
            Run(
                config=RunConfig.from_values({"x": 1}),
                state=RunState.RUNNING,
                wandb_run_id="wandb-run-id",
            )
        )

        assert run_id in optimizer.trials

    def test_an_unrelated_sampler_error_is_not_swallowed(self) -> None:
        class BrokenSampler(optuna.samplers.RandomSampler):
            def after_trial(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError("genuine sampler bug")

        study = optuna.create_study(direction="minimize", sampler=BrokenSampler())
        sweep = make_scheduler_grid_sweep(config=self.CONFIG)
        optimizer = OptunaDeclarativeOptimizer(study, self.DISTRIBUTIONS, sweep)
        suggestion = next(iter(optimizer.ask_n_runs(1)))

        with pytest.raises(RuntimeError, match="genuine sampler bug"):
            self.finish(optimizer, suggestion)


class TestImperativeWarmStart:
    """Define-by-run replays a finished run by enqueuing its params."""

    CONFIG = {
        "metric": {"name": "loss", "goal": "minimize"},
        "parameters": {"x": {"min": 0.0, "max": 1.0}},
    }

    @pytest.fixture
    def optimizer(self) -> OptunaImperativeOptimizer:
        study = optuna.create_study(
            direction="minimize", sampler=optuna.samplers.RandomSampler(seed=0)
        )
        sweep = make_scheduler_grid_sweep(config=self.CONFIG)
        return OptunaImperativeOptimizer(
            study, lambda trial: {"x": trial.suggest_float("x", 0.0, 1.0)}, sweep
        )

    def finished(self, x: float, loss: float) -> RunWithMetrics:
        return RunWithMetrics(
            config=RunConfig.from_values({"x": x}),
            state=RunState.FINISHED,
            wandb_run_id="wandb-run-id",
            summary_metrics={"loss": loss},
            history_metrics=[{"loss": loss, "_step": 0}],
        )

    def test_runs_sharing_a_config_each_record_their_own_params(
        self, optimizer
    ) -> None:
        """A skipped enqueue would tell a freshly sampled point this result."""
        optimizer.tell_existing_finished_run(self.finished(0.25, 1.0))
        optimizer.tell_existing_finished_run(self.finished(0.25, 2.0))

        trials = optimizer.study.get_trials(deepcopy=False)
        assert [trial.params["x"] for trial in trials] == [0.25, 0.25]
        assert [trial.values[0] for trial in trials] == [1.0, 2.0]


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
