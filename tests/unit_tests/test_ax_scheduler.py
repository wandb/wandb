from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

# ax-platform requires Python >= 3.11 (see requirements_dev.txt), so it's
# absent on 3.10 CI runs.
pytest.importorskip("ax")

import ax as ax_module
import wandb
from ax.api.client import Client
from ax.exceptions.core import DataRequiredError, OptimizationComplete
from ax.exceptions.generation_strategy import MaxParallelismReachedException
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.ax import (
    AxOptimizer,
    _experiment,
    _experiment_objectives,
    build_ax_optimizer,
    create_default_client,
    sweep_parameter_to_parameter,
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


class TestPruneRun:
    def test_a_client_without_an_early_stopping_strategy_never_prunes(
        self, client: Client, sweep: SweepInfo
    ) -> None:
        optimizer = AxOptimizer(client, sweep)
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        run = make_run(suggestion, state=RunState.RUNNING, summary={})
        with patch.object(client, "should_stop_trial_early") as should_stop:
            assert optimizer.prune_run(suggestion.run_id, run) is False

        should_stop.assert_not_called()


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
        config = {
            "metric": {"name": "loss", "goal": "minimize"},
            "parameters": {"x": {"distribution": "uniform", "min": 0.0, "max": 1.0}},
            "scheduler": {"engine": "ax"},
        }
        sweep = make_scheduler_grid_sweep(config=config)

        optimizer = build_ax_optimizer(sweep, config["scheduler"])

        assert isinstance(optimizer, AxOptimizer)
        assert optimizer.should_terminate_sweep() is False

    @pytest.mark.parametrize(
        "config, problem",
        [
            (
                {"parameters": {"x": {"distribution": "categorical"}}},
                "parameters.x is missing 'values'",
            ),
            (
                {"parameters": {"x": {"values": [None, 1]}}},
                "parameters.x is invalid: .*not None",
            ),
            (
                {"parameters": {"x": {"values": [{"a": 1}]}}},
                "parameters.x is invalid: .*not {'a': 1}",
            ),
            (
                {
                    "parameters": {
                        "x": {"distribution": "q_uniform", "min": 0, "max": 4, "q": 0}
                    }
                },
                "parameters.x is invalid: q must be positive",
            ),
            ({"parameters": {"x": {"min": 2.0, "max": 1.0}}}, "Upper bound of x"),
            ({"parameters": None}, "parameters must map"),
            ({"metric": None}, "set metric.name"),
        ],
        ids=[
            "no-values",
            "none-value",
            "dict-value",
            "zero-q",
            "inverted-bounds",
            "null-parameters",
            "null-metric",
        ],
    )
    def test_a_bad_sweep_config_is_a_wandb_error(
        self, config: dict[str, Any], problem: str
    ) -> None:
        config = {
            "metric": {"name": "loss", "goal": "minimize"},
            "parameters": {"x": {"min": 0.0, "max": 1.0}},
            **config,
        }
        sweep = make_scheduler_grid_sweep(config=config)

        with pytest.raises(wandb.Error, match=problem):
            build_ax_optimizer(sweep, {"engine": "ax"})

    @pytest.mark.parametrize(
        "factory, problem",
        [
            ("Client()", "no configured experiment"),
            (
                "make_client('loss')",
                "direction 'maximize' for 'loss' does not match",
            ),
        ],
        ids=["unconfigured", "goal-mismatch"],
    )
    def test_a_mismatched_client_is_a_wandb_error(
        self, tmp_path, factory: str, problem: str
    ) -> None:
        source = tmp_path / "optimizer.py"
        source.write_text(
            "from ax.api.client import Client\n"
            "from ax import RangeParameterConfig\n"
            "def make_client(objective):\n"
            "    client = Client()\n"
            "    client.configure_experiment(parameters=[RangeParameterConfig(\n"
            "        name='x', bounds=(0.0, 1.0), parameter_type='float')])\n"
            "    client.configure_optimization(objective=objective)\n"
            "    return client\n"
            f"def configure():\n    return {factory}\n",
            encoding="utf-8",
        )
        scheduler = {"engine": "ax", "source": str(source), "optimizer": "configure"}
        sweep = make_scheduler_grid_sweep(
            config={**DEFAULT_CONFIG, "scheduler": scheduler}
        )

        with pytest.raises(wandb.Error, match=problem):
            build_ax_optimizer(sweep, scheduler)


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


class TestRouteLibraryLogs:
    """Ax's records reach the handler the scheduler routes them to."""

    def test_captures_first_trial_generation(
        self,
        client: Client,
        sweep: SweepInfo,
        caplog: pytest.LogCaptureFixture,
        request: pytest.FixtureRequest,
    ) -> None:
        optimizer = AxOptimizer(client, sweep)

        request.addfinalizer(optimizer.route_library_logs(caplog.handler))
        optimizer.ask_n_runs(1)

        assert any(
            record.name.startswith("ax.") and "trial 0" in record.getMessage()
            for record in caplog.records
        )
