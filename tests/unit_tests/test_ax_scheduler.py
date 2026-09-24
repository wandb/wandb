from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

# ax-platform requires Python >= 3.11 (see requirements_dev.txt), so it's
# absent on 3.10 CI runs.
pytest.importorskip("ax")

import ax as ax_module
from ax.api.client import Client
from ax.exceptions.core import DataRequiredError, OptimizationComplete
from ax.exceptions.generation_strategy import MaxParallelismReachedException
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.ax import (
    AxOptimizer,
    _experiment,
    _experiment_objectives,
    create_default_client,
    sweep_parameter_to_parameter,
)
from wandb.sdk.sweeps.scheduler.optimizer import (
    Run,
    RunConfig,
    RunSuggestion,
    RunWithMetrics,
)
from wandb.sdk.sweeps.sweep_info import SweepInfo

from tests.unit_tests.test_sweep_scheduler import make_run, make_scheduler_grid_sweep

DEFAULT_CONFIG = {"metric": {"name": "loss", "goal": "minimize"}, "parameters": {}}


def make_client() -> Client:
    """Return an Ax `Client` with a single float parameter minimizing "loss"."""
    client = Client()
    client.configure_experiment(
        parameters=[
            ax_module.RangeParameterConfig(
                name="x", bounds=(0.0, 1.0), parameter_type="float"
            ),
        ]
    )
    client.configure_optimization(objective="-loss")
    return client


@pytest.fixture
def client() -> Client:
    return make_client()


@pytest.fixture
def sweep() -> SweepInfo:
    return make_scheduler_grid_sweep(config=DEFAULT_CONFIG)


class TestQDefault:
    """A missing `q` is 1 for both stepped distributions."""

    @pytest.mark.parametrize(
        ("parameter", "expected"),
        [
            (
                {"distribution": "q_uniform", "min": 0, "max": 10},
                ax_module.RangeParameterConfig(
                    name="x", bounds=(0.0, 10.0), parameter_type="int", step_size=1.0
                ),
            ),
            (
                {"distribution": "q_log_uniform_values", "min": 1, "max": 1000},
                ax_module.RangeParameterConfig(
                    name="x", bounds=(1, 1000), parameter_type="int", scaling="log"
                ),
            ),
        ],
        ids=["q_uniform", "q_log_uniform_values"],
    )
    def test_defaults_q_to_one(
        self, parameter: dict[str, Any], expected: ax_module.RangeParameterConfig
    ) -> None:
        assert sweep_parameter_to_parameter("x", parameter) == expected


class TestAskNRuns:
    """How `ask_n_runs` maps Ax's generation failures onto the contract."""

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            pytest.param(DataRequiredError("need data"), None, id="needs-more-data"),
            pytest.param(
                MaxParallelismReachedException(num_running=2),
                None,
                id="parallelism-cap",
            ),
            pytest.param(OptimizationComplete("done"), [], id="optimization-complete"),
        ],
    )
    def test_generation_failure_declines_or_finishes(
        self,
        client: Client,
        sweep: SweepInfo,
        error: Exception,
        expected: list[Any] | None,
    ) -> None:
        optimizer = AxOptimizer(client, sweep)
        with patch.object(client, "get_next_trials", side_effect=error):
            assert optimizer.ask_n_runs(2) == expected

    def test_propagates_unexpected_errors(
        self, client: Client, sweep: SweepInfo
    ) -> None:
        optimizer = AxOptimizer(client, sweep)
        with (
            patch.object(client, "get_next_trials", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            optimizer.ask_n_runs(2)


class TestForgetRun:
    def test_fails_the_forgotten_trial_once(
        self, client: Client, sweep: SweepInfo
    ) -> None:
        optimizer = AxOptimizer(client, sweep)
        with patch.object(client, "mark_trial_failed") as mark_failed:
            optimizer.forget_run("7")
            optimizer.forget_run("7")

        mark_failed.assert_called_once_with(trial_index=7)


class TestCreateDefaultClient:
    def test_configures_experiment_and_optimization_from_config(self) -> None:
        config = {
            "metric": {"name": "loss", "goal": "minimize"},
            "parameters": {"x": {"distribution": "uniform", "min": 0.0, "max": 1.0}},
        }

        client = create_default_client(config)

        experiment = _experiment(client)
        assert set(experiment.search_space.parameters) == {"x"}
        metric_names = experiment.optimization_config.objective.metric_names
        assert list(metric_names) == ["loss"]
        assert experiment.optimization_config.objective.minimize is True

    @pytest.mark.parametrize(
        ("name", "goal", "minimize"),
        [
            ("val-loss", "minimize", True),
            ("top 1 acc", "minimize", True),
            ("1_loss", "minimize", True),
            ("acc %", "minimize", True),
            ("accuracy", "maximize", False),
        ],
    )
    def test_objective_keeps_the_metric_name_and_goal(
        self, name: str, goal: str, minimize: bool
    ) -> None:
        """Names Ax's objective parser mangles or rejects survive verbatim."""
        config = {"metric": {"name": name, "goal": goal}, "parameters": {}}

        client = create_default_client(config)

        objective = _experiment(client).optimization_config.objective
        assert list(objective.metric_names) == [name]
        assert objective.minimize is minimize

    def test_metric_without_a_name_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="no metric name"):
            create_default_client({"metric": {"goal": "minimize"}, "parameters": {}})


class TestBuildAxSchedulerOptimizer:
    def test_builds_a_default_client(self) -> None:
        from wandb.cli import cli

        config = {
            "metric": {"name": "loss", "goal": "minimize"},
            "parameters": {"x": {"distribution": "uniform", "min": 0.0, "max": 1.0}},
            "scheduler": {"engine": "ax"},
        }
        sweep = make_scheduler_grid_sweep(config=config)

        optimizer = cli._build_ax_scheduler_optimizer(sweep, config["scheduler"])

        assert isinstance(optimizer, AxOptimizer)
        assert optimizer.should_terminate_sweep() is False


class TestUnparseableMetricName:
    def test_hyphenated_metric_completes_its_trial(self) -> None:
        """A name Ax's objective parser splits in two still drives a sweep."""
        config = {
            "metric": {"name": "val-loss", "goal": "minimize"},
            "parameters": {"x": {"distribution": "uniform", "min": 0.0, "max": 1.0}},
        }
        optimizer = AxOptimizer(
            create_default_client(config), make_scheduler_grid_sweep(config=config)
        )
        suggestion = next(iter(optimizer.ask_n_runs(1)))

        optimizer.tell_run(
            suggestion.run_id,
            make_run(suggestion, state=RunState.FINISHED, summary={"val-loss": 0.5}),
        )

        trial = _experiment(optimizer.client).trials[int(suggestion.run_id)]
        assert trial.status.is_completed
        assert optimizer.client.summarize()["val-loss"].tolist() == [0.5]


MULTI_OBJECTIVE_CONFIG = {
    "metrics": [
        {"name": "loss", "goal": "minimize"},
        {"name": "accuracy", "goal": "maximize"},
    ],
    "parameters": {"x": {"min": 0.0, "max": 1.0}},
}


class TestMultiObjective:
    """What Ax makes of a sweep that declares its objectives in `metrics`."""

    @pytest.fixture
    def optimizer(self) -> AxOptimizer:
        return AxOptimizer(
            create_default_client(MULTI_OBJECTIVE_CONFIG),
            make_scheduler_grid_sweep(config=MULTI_OBJECTIVE_CONFIG),
        )

    def test_creates_an_objective_per_declared_metric(
        self, optimizer: AxOptimizer
    ) -> None:
        objective = _experiment(optimizer.client).optimization_config.objective

        assert objective.is_multi_objective
        assert _experiment_objectives(optimizer.client) == [
            ("loss", True),
            ("accuracy", False),
        ]

    def test_intermediate_values_attach_every_objective(
        self, optimizer: AxOptimizer
    ) -> None:
        """Ax rejects partial data, so every objective is attached together."""
        suggestion = next(iter(optimizer.ask_n_runs(1)))

        optimizer.tell_run(
            suggestion.run_id,
            make_run(
                suggestion,
                state=RunState.RUNNING,
                summary={},
                history=[{"loss": 1.0, "accuracy": 0.3, "_step": 0}],
            ),
        )

        attached = _experiment(optimizer.client).lookup_data().df
        assert sorted(attached["metric_name"].unique()) == ["accuracy", "loss"]

    def test_a_mismatched_objective_count_is_rejected(self, client: Client) -> None:
        """A single-objective Ax client cannot serve a two-metric sweep."""
        sweep = make_scheduler_grid_sweep(config=MULTI_OBJECTIVE_CONFIG)

        with pytest.raises(ValueError, match="disagree on the objectives"):
            AxOptimizer(client, sweep)


class TestPersistedClientWarmStart:
    """A reloaded client already holding the sweep's trials is resumed.

    Each test drives one optimizer, saves its client to JSON, then rebuilds a
    second optimizer on the reloaded client, as a restarted scheduler would.
    """

    @pytest.fixture
    def reload(self, tmp_path, sweep: SweepInfo):
        path = str(tmp_path / "client.json")

        def reload(optimizer: AxOptimizer) -> AxOptimizer:
            optimizer.client.save_to_json_file(path)
            return AxOptimizer(Client.load_from_json_file(path), sweep)

        return reload

    def run(
        self,
        suggestion: RunSuggestion,
        state: RunState,
        history: list[dict[str, Any]],
    ) -> RunWithMetrics:
        return RunWithMetrics(
            config=suggestion.config,
            state=state,
            wandb_run_id="run-a",
            summary_metrics=history[-1] if history else {},
            history_metrics=history,
        )

    def trials(self, optimizer: AxOptimizer) -> dict[int, Any]:
        return _experiment(optimizer.client).trials

    def test_a_recorded_finished_run_is_not_attached_again(
        self, client: Client, sweep: SweepInfo, reload
    ) -> None:
        first = AxOptimizer(client, sweep)
        suggestion = next(iter(first.ask_n_runs(1)))
        finished = self.run(suggestion, RunState.FINISHED, [{"loss": 1.0, "_step": 0}])
        first.tell_run(suggestion.run_id, finished)

        second = reload(first)
        second.tell_existing_finished_run(finished)

        assert len(self.trials(second)) == 1

    def test_a_warm_started_run_is_not_attached_again(
        self, client: Client, sweep: SweepInfo, reload
    ) -> None:
        suggestion = RunSuggestion(
            config=RunConfig.from_values({"x": 0.5}), run_id="unused"
        )
        finished = self.run(suggestion, RunState.FINISHED, [{"loss": 1.0, "_step": 0}])
        first = AxOptimizer(client, sweep)
        first.tell_existing_finished_run(finished)

        second = reload(first)
        second.tell_existing_finished_run(finished)

        assert len(self.trials(second)) == 1

    def test_an_active_run_resumes_its_running_trial(
        self, client: Client, sweep: SweepInfo, reload
    ) -> None:
        first = AxOptimizer(client, sweep)
        suggestion = next(iter(first.ask_n_runs(1)))
        first.tell_run(
            suggestion.run_id,
            self.run(suggestion, RunState.RUNNING, [{"loss": 3.0, "_step": 0}]),
        )

        second = reload(first)
        run_id = second.tell_existing_active_run(
            self.run(suggestion, RunState.RUNNING, [])
        )
        second.tell_run(
            run_id,
            self.run(
                suggestion,
                RunState.FINISHED,
                [{"loss": 3.0, "_step": 0}, {"loss": 2.0, "_step": 1}],
            ),
        )

        (trial,) = self.trials(second).values()
        assert str(run_id) == suggestion.run_id
        assert trial.status.is_completed

    def test_an_unpolled_trial_is_matched_to_its_run_by_params(
        self, client: Client, sweep: SweepInfo, reload
    ) -> None:
        """A scheduler that stopped before the first poll never saw the run id."""
        first = AxOptimizer(client, sweep)
        suggestion = next(iter(first.ask_n_runs(1)))

        second = reload(first)
        run_id = second.tell_existing_active_run(
            self.run(suggestion, RunState.RUNNING, [])
        )

        assert str(run_id) == suggestion.run_id
        assert len(self.trials(second)) == 1

    def test_a_run_that_finished_unwatched_completes_its_trial(
        self, client: Client, sweep: SweepInfo, reload
    ) -> None:
        first = AxOptimizer(client, sweep)
        suggestion = next(iter(first.ask_n_runs(1)))
        first.tell_run(
            suggestion.run_id,
            self.run(suggestion, RunState.RUNNING, [{"loss": 3.0, "_step": 0}]),
        )

        second = reload(first)
        second.tell_existing_finished_run(
            self.run(suggestion, RunState.FINISHED, [{"loss": 2.0, "_step": 1}])
        )

        (trial,) = self.trials(second).values()
        assert trial.status.is_completed

    def test_an_active_run_whose_trial_finished_is_not_adopted(
        self, client: Client, sweep: SweepInfo, reload
    ) -> None:
        first = AxOptimizer(client, sweep)
        suggestion = next(iter(first.ask_n_runs(1)))
        running = self.run(suggestion, RunState.RUNNING, [{"loss": 3.0, "_step": 0}])
        first.tell_run(suggestion.run_id, running)
        first.forget_run(suggestion.run_id)

        second = reload(first)

        assert second.tell_existing_active_run(running) is None
        assert len(self.trials(second)) == 1

    def test_another_sweeps_running_trial_is_not_adopted(
        self, client: Client, sweep: SweepInfo
    ) -> None:
        foreign = client.attach_trial(parameters={"x": 0.5})
        optimizer = AxOptimizer(client, sweep)

        run_id = optimizer.tell_existing_active_run(
            Run(
                config=RunConfig.from_values({"x": 0.5}),
                state=RunState.RUNNING,
                wandb_run_id="run-a",
            )
        )

        assert run_id != foreign
