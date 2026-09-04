from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import optuna
import pytest
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.optimizer import (
    Run,
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


class TestQLogUniformValues:
    """optuna's log-scale int space only accepts `step=1` and `min >= 1`."""

    def test_maps_to_log_int_distribution(self) -> None:
        distribution = sweep_parameter_to_distribution(
            {"distribution": "q_log_uniform_values", "min": 1, "max": 1000}
        )

        assert distribution == optuna.distributions.IntDistribution(
            1, 1000, log=True, step=1
        )

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

    def test_hyperband_pruner_maps_max_iter_s_and_eta(self) -> None:
        study = create_study_from_sweep_config(
            {
                "metric": {"name": "loss"},
                "early_terminate": {
                    "type": "hyperband",
                    "max_iter": 27,
                    "s": 2,
                    "eta": 3,
                },
            }
        )

        pruner = study.pruner
        assert isinstance(pruner, optuna.pruners.HyperbandPruner)
        assert pruner._min_resource == 3
        assert pruner._max_resource == 27
        assert pruner._reduction_factor == 3

    def test_hyperband_pruner_maps_min_iter(self) -> None:
        study = create_study_from_sweep_config(
            {
                "metric": {"name": "loss"},
                "early_terminate": {
                    "type": "hyperband",
                    "min_iter": 3,
                    "eta": 3,
                },
            }
        )

        pruner = study.pruner
        assert isinstance(pruner, optuna.pruners.HyperbandPruner)
        assert pruner._min_resource == 3
        assert pruner._max_resource == "auto"
        assert pruner._reduction_factor == 3

    def test_no_early_terminate_uses_nop_pruner(self) -> None:
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


class TestGridExhaustion:
    """A finite sampler must finish the sweep instead of re-running the grid.

    optuna's GridSampler stops the study from `after_trial` once the grid is
    spent, and hands out duplicate grid points rather than refusing an ask.
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

    def test_tell_on_the_final_grid_point_records_the_trial(self, optimizer) -> None:
        """The sampler's stop request must not fail the run's tell."""
        suggestions = optimizer.ask_n_runs(2)

        for suggestion in suggestions:
            self.finish(optimizer, suggestion)

        trials = optimizer.study.get_trials(deepcopy=False)
        assert [trial.state for trial in trials] == [
            optuna.trial.TrialState.COMPLETE
        ] * 2

    def test_ask_returns_nothing_once_the_grid_is_spent(self, optimizer) -> None:
        for suggestion in optimizer.ask_n_runs(2):
            self.finish(optimizer, suggestion)

        assert optimizer.ask_n_runs(2) == []

    def test_ask_still_suggests_while_the_grid_is_in_flight(self, optimizer) -> None:
        """An empty batch finishes the sweep, so pending trials must not."""
        optimizer.ask_n_runs(2)

        assert optimizer.ask_n_runs(1) != []

    def test_ask_is_unbounded_for_a_sampler_without_a_grid(self) -> None:
        study = optuna.create_study(
            direction="minimize", sampler=optuna.samplers.TPESampler()
        )
        sweep = make_scheduler_grid_sweep(config=self.CONFIG)
        optimizer = OptunaDeclarativeOptimizer(study, self.DISTRIBUTIONS, sweep)

        assert len(optimizer.ask_n_runs(5)) == 5

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
