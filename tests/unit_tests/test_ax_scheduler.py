from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ax-platform requires Python >= 3.11 (see requirements_dev.txt), so it's
# absent on 3.10 CI runs.
pytest.importorskip("ax")

import ax as ax_module
from ax.api.client import Client
from wandb.sdk.sweeps.scheduler.ax import (
    AxOptimizer,
    AxOptions,
    _experiment,
    create_default_client,
    create_sweep,
    create_sweep_from_config,
    resume_sweep,
)
from wandb.sdk.sweeps.sweep_info import SweepInfo

from tests.unit_tests.test_sweep_scheduler import make_scheduler_grid_sweep

DEFAULT_CONFIG = {"metric": {"name": "loss", "goal": "minimize"}, "parameters": {}}

SWEEP_PATH = "test_entity/test_project/test_sweep"


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


@pytest.fixture
def run_scheduler_mock():
    """The entry points hand an optimizer factory to `run_scheduler`."""
    with patch("wandb.sdk.sweeps.scheduler.ax.run_scheduler") as run_scheduler:
        yield run_scheduler


@pytest.fixture
def wandb_sweep_mock():
    """The create-sweep entry points create the sweep through `wandb_sweep`."""
    with patch(
        "wandb.sdk.sweeps.scheduler.ax.wandb_sweep",
        return_value="test_sweep",
    ) as wandb_sweep:
        yield wandb_sweep


def built_optimizer(run_scheduler_mock: MagicMock, sweep: SweepInfo) -> Any:
    """Build the optimizer the captured factory produces for `sweep`."""
    return run_scheduler_mock.call_args.kwargs["make_optimizer"](sweep)


class TestResumeSweep:
    def test_builds_optimizer(
        self, run_scheduler_mock: MagicMock, client: Client, sweep: SweepInfo
    ) -> None:
        resume_sweep(SWEEP_PATH, options=AxOptions(client=client))

        kwargs = run_scheduler_mock.call_args.kwargs
        assert kwargs["entity"] == "test_entity"
        assert kwargs["project"] == "test_project"
        assert kwargs["sweep_id"] == "test_sweep"
        # No poll/batch given: defaults from `AxOptions()`.
        assert kwargs["poll_interval"] == AxOptions().poll_interval_s
        assert kwargs["batch_size"] == AxOptions().batch_size

        optimizer = built_optimizer(run_scheduler_mock, sweep)
        assert isinstance(optimizer, AxOptimizer)
        assert optimizer.client is client
        assert optimizer._sweep is sweep

    def test_requires_a_full_sweep_path(self, client: Client) -> None:
        with pytest.raises(ValueError, match="entity/project/sweep_id"):
            resume_sweep("bare-id", options=AxOptions(client=client))

    def test_uses_given_scheduler_options(
        self, run_scheduler_mock: MagicMock, client: Client
    ) -> None:
        resume_sweep(
            SWEEP_PATH,
            options=AxOptions(
                client=client,
                poll_interval_s=1.5,
                batch_size=3,
            ),
        )

        kwargs = run_scheduler_mock.call_args.kwargs
        assert kwargs["poll_interval"] == 1.5
        assert kwargs["batch_size"] == 3

    def test_requires_a_client(self) -> None:
        with pytest.raises(ValueError, match="client"):
            resume_sweep(SWEEP_PATH, options=AxOptions())

    def test_forwards_the_terminator_to_the_optimizer(
        self, run_scheduler_mock: MagicMock, client: Client, sweep: SweepInfo
    ) -> None:
        terminator = MagicMock()

        resume_sweep(
            SWEEP_PATH, options=AxOptions(client=client, terminator=terminator)
        )

        assert built_optimizer(run_scheduler_mock, sweep)._terminator is terminator


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


class TestCreateSweep:
    def test_builds_sweep_and_delegates(
        self,
        run_scheduler_mock: MagicMock,
        wandb_sweep_mock: MagicMock,
        client: Client,
        sweep: SweepInfo,
    ) -> None:
        create_sweep(
            "test_entity",
            "test_project",
            program_path="train.py",
            options=AxOptions(client=client),
        )

        wandb_sweep_mock.assert_called_once_with(
            {
                "metric": {"name": "loss", "goal": "minimize"},
                "parameters": {
                    "x": {"distribution": "uniform", "min": 0.0, "max": 1.0}
                },
                "scheduler": {"engine": "ax"},
                "program": "train.py",
            },
            entity="test_entity",
            project="test_project",
        )
        assert run_scheduler_mock.call_args.kwargs["sweep_id"] == "test_sweep"
        optimizer = built_optimizer(run_scheduler_mock, sweep)
        assert isinstance(optimizer, AxOptimizer)
        assert optimizer.client is client

    def test_requires_a_client(self) -> None:
        with pytest.raises(ValueError, match="client"):
            create_sweep("test_entity", "test_project", options=AxOptions())


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


class TestCreateSweepFromConfig:
    CONFIG = {
        "metric": {"name": "loss", "goal": "minimize"},
        "parameters": {"x": {"min": 0.0, "max": 1.0}},
    }

    def test_builds_sweep_and_optimizer_from_config(
        self,
        run_scheduler_mock: MagicMock,
        wandb_sweep_mock: MagicMock,
        client: Client,
        sweep: SweepInfo,
    ) -> None:
        create_sweep_from_config(
            self.CONFIG,
            "test_entity",
            "test_project",
            options=AxOptions(client=client),
        )

        wandb_sweep_mock.assert_called_once_with(
            {**self.CONFIG, "scheduler": {"engine": "ax"}},
            entity="test_entity",
            project="test_project",
        )
        kwargs = run_scheduler_mock.call_args.kwargs
        assert kwargs["sweep_id"] == "test_sweep"
        assert kwargs["poll_interval"] == AxOptions().poll_interval_s
        assert kwargs["batch_size"] == AxOptions().batch_size

        optimizer = built_optimizer(run_scheduler_mock, sweep)
        assert isinstance(optimizer, AxOptimizer)
        assert optimizer.client is client

    def test_builds_a_default_client_from_the_configs_goal_when_none_given(
        self, run_scheduler_mock: MagicMock, wandb_sweep_mock: MagicMock
    ) -> None:
        maximize_config = {
            "metric": {"name": "accuracy", "goal": "maximize"},
            "parameters": {},
        }

        create_sweep_from_config(maximize_config, "test_entity", "test_project")

        optimizer = built_optimizer(
            run_scheduler_mock, make_scheduler_grid_sweep(config=maximize_config)
        )
        objective = _experiment(optimizer.client).optimization_config.objective
        assert objective.minimize is False

    def test_uses_given_scheduler_options(
        self,
        run_scheduler_mock: MagicMock,
        wandb_sweep_mock: MagicMock,
        client: Client,
    ) -> None:
        create_sweep_from_config(
            self.CONFIG,
            "test_entity",
            "test_project",
            options=AxOptions(
                client=client,
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
        client: Client,
        sweep: SweepInfo,
    ) -> None:
        terminator = MagicMock()

        create_sweep_from_config(
            self.CONFIG,
            "test_entity",
            "test_project",
            options=AxOptions(client=client, terminator=terminator),
        )

        assert built_optimizer(run_scheduler_mock, sweep)._terminator is terminator

    def test_rejects_another_engine(self, client: Client) -> None:
        with pytest.raises(ValueError, match="optuna"):
            create_sweep_from_config(
                {"scheduler": {"engine": "optuna"}, "parameters": {}},
                "test_entity",
                "test_project",
                options=AxOptions(client=client),
            )


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
