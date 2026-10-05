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
    build_optuna_optimizer,
    create_study_from_sweep_config,
    make_optimizer,
    search_space_from_sweep_config,
    sweep_parameter_to_distribution,
)
from wandb.sdk.sweeps.sweep_info import SweepInfo

from tests.unit_tests.test_sweep_scheduler import make_run, make_scheduler_grid_sweep

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
    def test_builds_declarative_optimizer_from_parameters(self) -> None:
        config = {
            "metrics": [
                {"name": "loss", "goal": "minimize"},
                {"name": "accuracy", "goal": "maximize"},
            ],
            "parameters": {"lr": {"min": 0.0, "max": 1.0}},
            "scheduler": {"engine": "optuna"},
        }
        sweep = make_scheduler_grid_sweep(config=config)

        optimizer = build_optuna_optimizer(sweep, config["scheduler"])

        assert isinstance(optimizer, OptunaDeclarativeOptimizer)

    def test_builds_imperative_optimizer_from_search_space(self, tmp_path) -> None:
        source = tmp_path / "search_space.py"
        source.write_text(
            "def define_by_run(trial):\n"
            "    return {'lr': trial.suggest_float('lr', 0.0, 1.0)}\n",
            encoding="utf-8",
        )
        config = {
            "metric": {"name": "loss", "goal": "minimize"},
            "parameters": {},
            "scheduler": {
                "engine": "optuna",
                "source": str(source),
                "search_space": "define_by_run",
            },
        }
        sweep = make_scheduler_grid_sweep(config=config)

        optimizer = build_optuna_optimizer(sweep, config["scheduler"])

        assert isinstance(optimizer, OptunaImperativeOptimizer)


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

    def drain(self, optimizer, max_runs: int = 10) -> list[dict[str, Any]]:
        """Finish every proposed run until the grid is spent or the cap hits."""
        configs = []
        while len(configs) < max_runs and (batch := optimizer.ask_n_runs(2)):
            for suggestion in batch:
                configs.append(suggestion.config.flat_dict())
                self.finish(optimizer, suggestion)
        return configs

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

    def test_a_large_ask_proposes_each_grid_point_once(self, optimizer) -> None:
        suggestions = optimizer.ask_n_runs(5)

        points = sorted(s.config.flat_dict()["x"] for s in suggestions)
        assert points == [1, 2]

    def test_ask_skips_grid_points_in_flight(self, optimizer) -> None:
        """The scheduler waits out in-flight runs after an empty batch."""
        first = optimizer.ask_n_runs(1)
        second = optimizer.ask_n_runs(2)

        assert first[0].config.flat_dict() != second[0].config.flat_dict()
        assert len(second) == 1
        assert optimizer.ask_n_runs(1) == []

    def test_a_forgotten_grid_point_is_proposed_again(self, optimizer) -> None:
        """Go never asks after an empty batch, so ipc.py forgets first."""
        forgotten, kept = optimizer.ask_n_runs(2)
        optimizer.forget_run(forgotten.run_id)
        self.finish(optimizer, kept)

        again = optimizer.ask_n_runs(2)

        assert [s.config.flat_dict() for s in again] == [forgotten.config.flat_dict()]
        self.finish(optimizer, again[0])
        assert optimizer.ask_n_runs(2) == []

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

    def test_ask_skips_the_point_of_an_adopted_run(self, optimizer) -> None:
        optimizer.tell_existing_active_run(
            Run(
                config=RunConfig.from_values({"x": 1}),
                state=RunState.RUNNING,
                wandb_run_id="wandb-run-id",
            )
        )

        suggestions = optimizer.ask_n_runs(2)

        assert [s.config.flat_dict() for s in suggestions] == [{"x": 2}]

    def test_ask_skips_the_point_of_a_warm_started_run(self, optimizer) -> None:
        optimizer.tell_existing_finished_run(
            RunWithMetrics(
                config=RunConfig.from_values({"x": 1}),
                state=RunState.FINISHED,
                wandb_run_id="wandb-run-id",
                summary_metrics={"loss": 0.5},
                history_metrics=[],
            )
        )

        suggestions = optimizer.ask_n_runs(2)

        assert [s.config.flat_dict() for s in suggestions] == [{"x": 2}]

    def test_a_single_point_grid_finishes_its_run(self) -> None:
        """GridSampler's grid id lookup must not fail an enqueued trial."""
        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.GridSampler({"x": [1]}),
        )
        sweep = make_scheduler_grid_sweep(config=self.CONFIG)
        optimizer = OptunaDeclarativeOptimizer(study, self.DISTRIBUTIONS, sweep)

        self.finish(optimizer, optimizer.ask_n_runs(2)[0])

        trial = study.get_trials(deepcopy=False)[0]
        assert trial.state == optuna.trial.TrialState.COMPLETE
        assert optimizer.ask_n_runs(2) == []

    def test_a_conditional_define_by_run_grid_is_exhausted(self) -> None:
        """A branch that skips a grid key covers every value of that key."""

        def search_space(trial: optuna.Trial) -> dict[str, Any]:
            params = {"opt": trial.suggest_categorical("opt", ["sgd", "adam"])}
            if params["opt"] == "sgd":
                params["mom"] = trial.suggest_categorical("mom", [0.9, 0.99])
            return params

        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.GridSampler(
                {"opt": ["sgd", "adam"], "mom": [0.9, 0.99]}
            ),
        )
        sweep = make_scheduler_grid_sweep(config=self.CONFIG)
        optimizer = OptunaImperativeOptimizer(study, search_space, sweep)

        suggestions = optimizer.ask_n_runs(5)
        for suggestion in suggestions:
            self.finish(optimizer, suggestion)

        assert sorted(str(s.config.flat_dict()) for s in suggestions) == [
            "{'opt': 'adam'}",
            "{'opt': 'sgd', 'mom': 0.99}",
            "{'opt': 'sgd', 'mom': 0.9}",
        ]
        assert optimizer.ask_n_runs(5) == []

    def test_a_constant_parameter_outside_the_grid_is_exhausted(self) -> None:
        parameters = {"x": {"values": [1, 2]}, "epochs": {"value": 10}}
        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.GridSampler({"x": [1, 2]}),
        )
        sweep = make_scheduler_grid_sweep(
            config={**self.CONFIG, "parameters": parameters}
        )
        optimizer = OptunaDeclarativeOptimizer(
            study, search_space_from_sweep_config(parameters), sweep
        )

        configs = self.drain(optimizer)

        assert sorted(c["x"] for c in configs) == [1, 2]

    def test_a_nan_grid_value_is_proposed_once(self) -> None:
        """Distinct NaN objects, as a grid and a search space each hold one."""
        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.GridSampler({"x": [1.0, float("nan")]}),
        )
        sweep = make_scheduler_grid_sweep(config=self.CONFIG)
        optimizer = OptunaImperativeOptimizer(
            study,
            lambda trial: {"x": trial.suggest_categorical("x", [1.0, float("nan")])},
            sweep,
        )

        configs = self.drain(optimizer)

        assert len(configs) == 2

    @pytest.mark.parametrize("seed", [0, 1, 2])
    def test_grid_points_follow_the_sampler_seed(self, seed: int) -> None:
        grid = {"x": [1, 2, 3]}
        reference = optuna.create_study(
            sampler=optuna.samplers.GridSampler(grid, seed=seed)
        )
        expected = [
            reference.ask().suggest_categorical("x", grid["x"]) for _ in grid["x"]
        ]
        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.GridSampler(grid, seed=seed),
        )
        sweep = make_scheduler_grid_sweep(config=self.CONFIG)
        optimizer = OptunaDeclarativeOptimizer(
            study, {"x": optuna.distributions.CategoricalDistribution([1, 2, 3])}, sweep
        )

        suggestions = optimizer.ask_n_runs(3)

        assert [s.config.flat_dict()["x"] for s in suggestions] == expected

    def test_a_sweep_parameter_outside_the_grid_is_named(self) -> None:
        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.GridSampler({"x": [1, 2]}),
        )
        sweep = make_scheduler_grid_sweep(config=self.CONFIG)
        distributions = {
            **self.DISTRIBUTIONS,
            "lr": optuna.distributions.FloatDistribution(0.0, 1.0),
        }
        optimizer = OptunaDeclarativeOptimizer(study, distributions, sweep)

        with pytest.raises(ValueError, match=r"\['lr'\].*`value`"):
            optimizer.ask_n_runs(1)

    def test_a_suggestion_outside_the_grid_names_the_search_space(self) -> None:
        def search_space(trial: optuna.Trial) -> dict[str, Any]:
            return {
                "x": trial.suggest_categorical("x", [1, 2]),
                "lr": trial.suggest_float("lr", 0.0, 1.0),
            }

        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.GridSampler({"x": [1, 2]}),
        )
        sweep = make_scheduler_grid_sweep(config=self.CONFIG)
        optimizer = OptunaImperativeOptimizer(study, search_space, sweep)

        with pytest.raises(ValueError, match=r"`scheduler.search_space`.*\['x'\]"):
            optimizer.ask_n_runs(1)

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


class TestRouteLibraryLogs:
    """Optuna's records reach the handler the scheduler routes them to."""

    @pytest.fixture
    def optimizer(
        self, study: optuna.Study, sweep: SweepInfo
    ) -> OptunaDeclarativeOptimizer:
        distributions = {"x": optuna.distributions.FloatDistribution(0.0, 1.0)}
        return OptunaDeclarativeOptimizer(study, distributions, sweep)

    def test_captures_study_creation(
        self,
        optimizer: OptunaDeclarativeOptimizer,
        caplog: pytest.LogCaptureFixture,
        request: pytest.FixtureRequest,
    ) -> None:
        request.addfinalizer(optimizer.route_library_logs(caplog.handler))
        optuna.create_study(study_name="routed-study")

        assert any(
            record.name.startswith("optuna.") and "routed-study" in record.getMessage()
            for record in caplog.records
        )

    def test_captures_trial_outcome(
        self,
        optimizer: OptunaDeclarativeOptimizer,
        caplog: pytest.LogCaptureFixture,
        request: pytest.FixtureRequest,
    ) -> None:
        request.addfinalizer(optimizer.route_library_logs(caplog.handler))
        suggestion = optimizer.ask_n_runs(1)[0]
        optimizer.tell_run(
            suggestion.run_id,
            make_run(suggestion, state=RunState.FINISHED, summary={"loss": 1.0}),
        )

        assert [record.name for record in caplog.records] == ["optuna.wandb_scheduler"]
