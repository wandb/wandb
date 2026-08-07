from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ax-platform requires Python >= 3.11 (see requirements_dev.txt), so it's
# absent on 3.10 CI runs.
pytest.importorskip("ax")

import ax as ax_module
from ax.api.client import Client
from wandb.apis.public import Sweep
from wandb.sdk.sweeps.scheduler.ax import (
    AxOptimizer,
    AxOptions,
    create_default_client,
    create_sweep,
    create_sweep_from_config,
    resume_sweep,
)
from wandb.sdk.sweeps.scheduler.scheduler import (
    Executor,
    InMemoryScheduler,
    WBAgentExecutor,
)

from tests.unit_tests.test_sweep_scheduler import make_scheduler_grid_sweep

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
def sweep() -> Sweep:
    return make_scheduler_grid_sweep(config=DEFAULT_CONFIG)


@pytest.fixture(autouse=True)
def mock_scheduler_api() -> Any:
    """`InMemoryScheduler.__init__` calls `Api()`; keep it from hitting the network."""
    with patch("wandb.sdk.sweeps.scheduler.scheduler.Api", return_value=MagicMock()):
        yield


class TestResumeSweep:
    def test_builds_optimizer_and_default_scheduler(
        self, client: Client, sweep: Sweep
    ) -> None:
        result = resume_sweep(sweep, options=AxOptions(client=client))

        assert isinstance(result, InMemoryScheduler)
        assert isinstance(result._optimizer, AxOptimizer)
        assert result._optimizer.client is client
        assert result._optimizer._sweep is sweep
        assert result._sweep is sweep
        # No poll/batch/executor given: defaults from `AxOptions()`.
        assert result._poll_interval_s == AxOptions().poll_interval_s
        assert result._batch_size == AxOptions().batch_size
        assert isinstance(result._executor, WBAgentExecutor)

    def test_resolves_sweep_given_as_path_string(
        self, client: Client, sweep: Sweep
    ) -> None:
        api = MagicMock()
        api.sweep.return_value = sweep
        with patch("wandb.sdk.sweeps.scheduler.ax.Api", return_value=api):
            result = resume_sweep(
                "test_entity/test_project/test_sweep",
                options=AxOptions(client=client),
            )

        api.sweep.assert_called_once_with("test_entity/test_project/test_sweep")
        assert result._sweep is sweep

    def test_uses_given_scheduler_options(self, client: Client, sweep: Sweep) -> None:
        executor = MagicMock(spec=Executor)

        result = resume_sweep(
            sweep,
            options=AxOptions(
                client=client,
                poll_interval_s=1.5,
                batch_size=3,
                executor=executor,
            ),
        )

        assert result._poll_interval_s == 1.5
        assert result._batch_size == 3
        assert result._executor is executor

    def test_requires_a_client(self, sweep: Sweep) -> None:
        with pytest.raises(ValueError, match="client"):
            resume_sweep(sweep, options=AxOptions())

    def test_forwards_the_terminator_to_the_optimizer(
        self, client: Client, sweep: Sweep
    ) -> None:
        terminator = MagicMock()

        result = resume_sweep(
            sweep, options=AxOptions(client=client, terminator=terminator)
        )

        assert result._optimizer._terminator is terminator


class TestCreateSweep:
    def test_builds_sweep_and_delegates(self, client: Client, sweep: Sweep) -> None:
        api = MagicMock()
        api.sweep.return_value = sweep
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.ax.wandb_sweep",
                return_value="test_sweep",
            ) as mock_wandb_sweep,
            patch("wandb.sdk.sweeps.scheduler.ax.Api", return_value=api),
        ):
            result = create_sweep(
                "test_entity",
                "test_project",
                program_path="train.py",
                options=AxOptions(client=client),
            )

        mock_wandb_sweep.assert_called_once_with(
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
        api.sweep.assert_called_once_with("test_entity/test_project/test_sweep")
        assert isinstance(result, InMemoryScheduler)
        assert isinstance(result._optimizer, AxOptimizer)
        assert result._optimizer.client is client
        assert result._sweep is sweep

    def test_requires_a_client(self) -> None:
        with pytest.raises(ValueError, match="client"):
            create_sweep("test_entity", "test_project", options=AxOptions())

    def test_forwards_the_terminator_to_the_optimizer(
        self, client: Client, sweep: Sweep
    ) -> None:
        terminator = MagicMock()
        api = MagicMock()
        api.sweep.return_value = sweep
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.ax.wandb_sweep",
                return_value="test_sweep",
            ),
            patch("wandb.sdk.sweeps.scheduler.ax.Api", return_value=api),
        ):
            result = create_sweep(
                "test_entity",
                "test_project",
                options=AxOptions(client=client, terminator=terminator),
            )

        assert result._optimizer._terminator is terminator


class TestCreateDefaultClient:
    def test_configures_experiment_and_optimization_from_config(self) -> None:
        config = {
            "metric": {"name": "loss", "goal": "minimize"},
            "parameters": {"x": {"distribution": "uniform", "min": 0.0, "max": 1.0}},
        }

        client = create_default_client(config)

        experiment = client._experiment
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

        assert client._experiment.optimization_config.objective.minimize is False


class TestCreateSweepFromConfig:
    CONFIG = {
        "metric": {"name": "loss", "goal": "minimize"},
        "parameters": {"x": {"min": 0.0, "max": 1.0}},
    }

    def test_builds_sweep_and_optimizer_from_config(
        self, client: Client, sweep: Sweep
    ) -> None:
        api = MagicMock()
        api.sweep.return_value = sweep
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.ax.wandb_sweep",
                return_value="test_sweep",
            ) as mock_wandb_sweep,
            patch("wandb.sdk.sweeps.scheduler.ax.Api", return_value=api),
        ):
            result = create_sweep_from_config(
                self.CONFIG,
                "test_entity",
                "test_project",
                options=AxOptions(client=client),
            )

        mock_wandb_sweep.assert_called_once_with(
            self.CONFIG, entity="test_entity", project="test_project"
        )
        api.sweep.assert_called_once_with("test_entity/test_project/test_sweep")

        assert isinstance(result, InMemoryScheduler)
        assert isinstance(result._optimizer, AxOptimizer)
        assert result._optimizer.client is client
        assert result._sweep is sweep
        assert result._poll_interval_s == AxOptions().poll_interval_s
        assert result._batch_size == AxOptions().batch_size
        assert isinstance(result._executor, WBAgentExecutor)

    def test_builds_a_default_client_from_the_configs_goal_when_none_given(
        self,
    ) -> None:
        maximize_config = {
            "metric": {"name": "accuracy", "goal": "maximize"},
            "parameters": {},
        }
        api = MagicMock()
        api.sweep.return_value = make_scheduler_grid_sweep(config=maximize_config)
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.ax.wandb_sweep",
                return_value="test_sweep",
            ),
            patch("wandb.sdk.sweeps.scheduler.ax.Api", return_value=api),
        ):
            result = create_sweep_from_config(
                maximize_config, "test_entity", "test_project"
            )

        objective = result._optimizer.client._experiment.optimization_config.objective
        assert objective.minimize is False

    def test_uses_given_scheduler_options(self, client: Client, sweep: Sweep) -> None:
        executor = MagicMock(spec=Executor)
        api = MagicMock()
        api.sweep.return_value = sweep
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.ax.wandb_sweep",
                return_value="test_sweep",
            ),
            patch("wandb.sdk.sweeps.scheduler.ax.Api", return_value=api),
        ):
            result = create_sweep_from_config(
                self.CONFIG,
                "test_entity",
                "test_project",
                options=AxOptions(
                    client=client,
                    poll_interval_s=2.5,
                    batch_size=7,
                    executor=executor,
                ),
            )

        assert result._poll_interval_s == 2.5
        assert result._batch_size == 7
        assert result._executor is executor

    def test_forwards_the_terminator_to_the_optimizer(
        self, client: Client, sweep: Sweep
    ) -> None:
        terminator = MagicMock()
        api = MagicMock()
        api.sweep.return_value = sweep
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.ax.wandb_sweep",
                return_value="test_sweep",
            ),
            patch("wandb.sdk.sweeps.scheduler.ax.Api", return_value=api),
        ):
            result = create_sweep_from_config(
                self.CONFIG,
                "test_entity",
                "test_project",
                options=AxOptions(client=client, terminator=terminator),
            )

        assert result._optimizer._terminator is terminator
