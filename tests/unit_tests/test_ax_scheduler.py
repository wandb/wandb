from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ax-platform requires Python >= 3.11 (see requirements_dev.txt), so it's
# absent on 3.10 CI runs.
pytest.importorskip("ax")

import ax as ax_module
from ax.api.client import Client
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.ax import (
    AxOptimizer,
    _experiment,
    create_default_client,
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


class TestAskNRuns:
    """How `ask_n_runs` maps Ax's generation failures onto the contract."""

    def test_declines_with_none_when_ax_needs_more_data(
        self, client: Client, sweep: SweepInfo
    ) -> None:
        from ax.exceptions.core import DataRequiredError

        optimizer = AxOptimizer(client, sweep)
        with patch.object(
            client, "get_next_trials", side_effect=DataRequiredError("need data")
        ):
            assert optimizer.ask_n_runs(2) is None

    def test_declines_with_none_when_parallelism_cap_is_hit(
        self, client: Client, sweep: SweepInfo
    ) -> None:
        from ax.exceptions.generation_strategy import MaxParallelismReachedException

        optimizer = AxOptimizer(client, sweep)
        with patch.object(
            client,
            "get_next_trials",
            side_effect=MaxParallelismReachedException(num_running=2),
        ):
            assert optimizer.ask_n_runs(2) is None

    def test_finishes_with_empty_when_optimization_complete(
        self, client: Client, sweep: SweepInfo
    ) -> None:
        from ax.exceptions.core import OptimizationComplete

        optimizer = AxOptimizer(client, sweep)
        with patch.object(
            client, "get_next_trials", side_effect=OptimizationComplete("done")
        ):
            assert optimizer.ask_n_runs(2) == []

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

    def test_maximize_goal_sets_minimize_false(self) -> None:
        config = {
            "metric": {"name": "accuracy", "goal": "maximize"},
            "parameters": {},
        }

        client = create_default_client(config)

        assert _experiment(client).optimization_config.objective.minimize is False

    @pytest.mark.parametrize("name", ["val-loss", "top 1 acc", "1_loss", "acc %"])
    def test_metric_name_ax_cannot_parse_is_kept_whole(self, name: str) -> None:
        """Names Ax's objective parser mangles or rejects survive verbatim."""
        config = {"metric": {"name": name, "goal": "minimize"}, "parameters": {}}

        client = create_default_client(config)

        objective = _experiment(client).optimization_config.objective
        assert list(objective.metric_names) == [name]
        assert objective.minimize is True

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

    def test_optimizer_config_returns_client(
        self, monkeypatch, client: Client, sweep: SweepInfo
    ) -> None:
        from wandb.cli import cli

        configure = MagicMock(return_value=client)
        monkeypatch.setattr(cli, "_load_source_object", lambda *_: configure)

        optimizer = cli._build_ax_scheduler_optimizer(
            sweep,
            {"engine": "ax", "source": "optimizer.py", "optimizer": "configure"},
        )

        assert optimizer.client is client
        assert optimizer.should_terminate_sweep() is False

    def test_optimizer_config_returns_client_and_terminator(
        self, monkeypatch, client: Client, sweep: SweepInfo
    ) -> None:
        from wandb.cli import cli

        terminator = MagicMock(return_value=True)
        configure = MagicMock(return_value=(client, terminator))
        monkeypatch.setattr(cli, "_load_source_object", lambda *_: configure)

        optimizer = cli._build_ax_scheduler_optimizer(
            sweep,
            {"engine": "ax", "source": "optimizer.py", "optimizer": "configure"},
        )

        assert optimizer.client is client
        assert optimizer.should_terminate_sweep() is True
        terminator.assert_called_once_with(client)


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


class TestMultiObjectiveRejected:
    def test_multi_objective_sweep_is_rejected_clearly(self, client: Client) -> None:
        """Ax optimizes one scalar objective; say so up front."""
        metrics_config = {
            "metrics": [
                {"name": "loss", "goal": "minimize"},
                {"name": "accuracy", "goal": "maximize"},
            ],
            "parameters": {"x": {"min": 0.0, "max": 1.0}},
        }
        sweep = make_scheduler_grid_sweep(config=metrics_config)

        with pytest.raises(ValueError, match="single-objective"):
            AxOptimizer(client, sweep)
