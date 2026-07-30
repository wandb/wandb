from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import optuna
import pytest
from wandb.apis.public import Sweep
from wandb.sdk.sweeps.scheduler.optuna import (
    OptunaDeclarativeOptimizer,
    OptunaImperativeOptimizer,
    OptunaOptions,
    create_study_from_sweep_config,
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

optuna.logging.set_verbosity(optuna.logging.WARNING)


DEFAULT_CONFIG = {"metric": {"name": "loss", "goal": "minimize"}, "parameters": {}}


@pytest.fixture
def sweep() -> Sweep:
    return make_scheduler_grid_sweep(config=DEFAULT_CONFIG)


@pytest.fixture
def study() -> optuna.Study:
    return optuna.create_study(direction="minimize")


@pytest.fixture(autouse=True)
def mock_scheduler_api() -> Any:
    """`InMemoryScheduler.__init__` calls `Api()`; keep it from hitting the network."""
    with patch("wandb.sdk.sweeps.scheduler.scheduler.Api", return_value=MagicMock()):
        yield


class TestResumeSweep:
    def test_builds_declarative_optimizer_and_default_scheduler(
        self, study: optuna.Study, sweep: Sweep
    ) -> None:
        distributions = {"x": optuna.distributions.FloatDistribution(0.0, 1.0)}

        result = resume_sweep(
            sweep, options=OptunaOptions(study=study, distributions=distributions)
        )

        assert isinstance(result, InMemoryScheduler)
        assert isinstance(result._optimizer, OptunaDeclarativeOptimizer)
        assert result._optimizer.study is study
        assert result._optimizer.distributions is distributions
        assert result._optimizer._sweep is sweep
        assert result._sweep is sweep
        # No poll/batch/executor given: defaults from `OptunaOptions()`.
        assert result._poll_interval_s == OptunaOptions().poll_interval_s
        assert result._batch_size == OptunaOptions().batch_size
        assert isinstance(result._executor, WBAgentExecutor)

    def test_builds_imperative_optimizer(
        self, study: optuna.Study, sweep: Sweep
    ) -> None:
        def trial_constructor(trial: optuna.Trial) -> dict[str, Any]:
            return {"x": trial.suggest_float("x", 0.0, 1.0)}

        result = resume_sweep(
            sweep, options=OptunaOptions(study=study, search_space=trial_constructor)
        )

        assert isinstance(result._optimizer, OptunaImperativeOptimizer)
        assert result._optimizer.trial_constructor is trial_constructor

    def test_resolves_sweep_given_as_path_string(
        self, study: optuna.Study, sweep: Sweep
    ) -> None:
        api = MagicMock()
        api.sweep.return_value = sweep
        with patch("wandb.sdk.sweeps.scheduler.optuna.Api", return_value=api):
            result = resume_sweep(
                "test_entity/test_project/test_sweep",
                options=OptunaOptions(study=study, distributions={}),
            )

        api.sweep.assert_called_once_with("test_entity/test_project/test_sweep")
        assert result._sweep is sweep

    def test_uses_given_scheduler_options(
        self, study: optuna.Study, sweep: Sweep
    ) -> None:
        executor = MagicMock(spec=Executor)

        result = resume_sweep(
            sweep,
            options=OptunaOptions(
                study=study,
                distributions={},
                poll_interval_s=1.5,
                batch_size=3,
                executor=executor,
            ),
        )

        assert result._poll_interval_s == 1.5
        assert result._batch_size == 3
        assert result._executor is executor

    def test_requires_a_study(self, sweep: Sweep) -> None:
        with pytest.raises(ValueError, match="study"):
            resume_sweep(sweep, options=OptunaOptions(distributions={}))

    @pytest.mark.parametrize(
        "extra",
        [
            {},
            {"distributions": {}, "search_space": lambda trial: {}},
        ],
        ids=["neither", "both"],
    )
    def test_requires_exactly_one_of_distributions_or_search_space(
        self, study: optuna.Study, sweep: Sweep, extra: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            resume_sweep(sweep, options=OptunaOptions(study=study, **extra))

    def test_forwards_the_terminator_to_the_optimizer(
        self, study: optuna.Study, sweep: Sweep
    ) -> None:
        terminator = MagicMock()

        result = resume_sweep(
            sweep,
            options=OptunaOptions(study=study, distributions={}, terminator=terminator),
        )

        assert result._optimizer._terminator is terminator


class TestCreateSweep:
    def test_declarative_path_builds_sweep_and_delegates(
        self, study: optuna.Study, sweep: Sweep
    ) -> None:
        distributions = {"lr": optuna.distributions.FloatDistribution(0.0, 1.0)}
        api = MagicMock()
        api.sweep.return_value = sweep
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.optuna.wandb_sweep",
                return_value="test_sweep",
            ) as mock_wandb_sweep,
            patch("wandb.sdk.sweeps.scheduler.optuna.Api", return_value=api),
        ):
            result = create_sweep(
                "test_entity",
                "test_project",
                "loss",
                program_path="train.py",
                options=OptunaOptions(study=study, distributions=distributions),
            )

        mock_wandb_sweep.assert_called_once_with(
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
        api.sweep.assert_called_once_with("test_entity/test_project/test_sweep")
        assert isinstance(result, InMemoryScheduler)
        assert isinstance(result._optimizer, OptunaDeclarativeOptimizer)
        assert result._optimizer.distributions is distributions
        assert result._sweep is sweep

    def test_imperative_path_discovers_space_and_keeps_the_constructor(
        self, study: optuna.Study, sweep: Sweep
    ) -> None:
        """Regression test: the discovered space must not overwrite the
        constructor that `resume_sweep` needs to build the imperative
        optimizer -- `create_sweep` used to shadow its `search_space`
        parameter with the discovered distributions dict before forwarding
        it, silently swapping the callable for a dict.
        """

        def trial_constructor(trial: optuna.Trial) -> dict[str, Any]:
            return {"lr": trial.suggest_float("lr", 0.0, 1.0)}

        api = MagicMock()
        api.sweep.return_value = sweep
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.optuna.wandb_sweep",
                return_value="test_sweep",
            ) as mock_wandb_sweep,
            patch("wandb.sdk.sweeps.scheduler.optuna.Api", return_value=api),
        ):
            result = create_sweep(
                "test_entity",
                "test_project",
                "loss",
                options=OptunaOptions(study=study, search_space=trial_constructor),
            )

        # The space `_spy_search_space` discovered by really running
        # `trial_constructor` made it into the sweep the server was asked to
        # create.
        sent_config = mock_wandb_sweep.call_args[0][0]
        assert sent_config["parameters"] == {
            "lr": {"distribution": "uniform", "min": 0.0, "max": 1.0}
        }
        # But the optimizer that drives the rest of the sweep keeps the
        # original callable, not that discovered dict.
        assert isinstance(result._optimizer, OptunaImperativeOptimizer)
        assert result._optimizer.trial_constructor is trial_constructor

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

    def test_forwards_the_terminator_to_the_optimizer(
        self, study: optuna.Study, sweep: Sweep
    ) -> None:
        terminator = MagicMock()
        api = MagicMock()
        api.sweep.return_value = sweep
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.optuna.wandb_sweep",
                return_value="test_sweep",
            ),
            patch("wandb.sdk.sweeps.scheduler.optuna.Api", return_value=api),
        ):
            result = create_sweep(
                "test_entity",
                "test_project",
                "loss",
                options=OptunaOptions(
                    study=study, distributions={}, terminator=terminator
                ),
            )

        assert result._optimizer._terminator is terminator


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

    def test_multi_objective_study_passes_validation(self) -> None:
        metrics_config = {
            "metrics": [
                {"name": "loss", "goal": "minimize"},
                {"name": "accuracy", "goal": "maximize"},
            ],
            "parameters": {},
        }
        study = create_study_from_sweep_config(metrics_config)
        sweep = make_scheduler_grid_sweep(config=metrics_config)

        OptunaDeclarativeOptimizer(study, {}, sweep)


class TestBuildOptunaScheduler:
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
        scheduler = MagicMock()
        with patch(
            "wandb.sdk.sweeps.scheduler.optuna.resume_sweep", return_value=scheduler
        ) as resume_sweep:
            result = cli._build_optuna_scheduler(
                sweep, config, config["scheduler"], poll_interval=5.0, batch_size=10
            )

        resume_sweep.assert_called_once()
        options = resume_sweep.call_args.kwargs["options"]
        assert [d.name.lower() for d in options.study.directions] == [
            "minimize",
            "maximize",
        ]
        assert result is scheduler


class TestCreateSweepFromConfig:
    CONFIG = {
        "metric": {"name": "loss", "goal": "minimize"},
        "parameters": {"lr": {"min": 0.0, "max": 1.0}},
    }

    def test_builds_sweep_and_declarative_optimizer_from_config(
        self, study: optuna.Study, sweep: Sweep
    ) -> None:
        api = MagicMock()
        api.sweep.return_value = sweep
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.optuna.wandb_sweep",
                return_value="test_sweep",
            ) as mock_wandb_sweep,
            patch("wandb.sdk.sweeps.scheduler.optuna.Api", return_value=api),
        ):
            result = create_sweep_from_config(
                self.CONFIG,
                "test_entity",
                "test_project",
                options=OptunaOptions(study=study),
            )

        mock_wandb_sweep.assert_called_once_with(
            self.CONFIG, entity="test_entity", project="test_project"
        )
        api.sweep.assert_called_once_with("test_entity/test_project/test_sweep")

        assert isinstance(result, InMemoryScheduler)
        assert isinstance(result._optimizer, OptunaDeclarativeOptimizer)
        assert result._optimizer.study is study
        assert result._optimizer.distributions == {
            "lr": optuna.distributions.FloatDistribution(0.0, 1.0)
        }
        assert result._sweep is sweep
        assert result._poll_interval_s == OptunaOptions().poll_interval_s
        assert result._batch_size == OptunaOptions().batch_size
        assert isinstance(result._executor, WBAgentExecutor)

    def test_creates_a_study_from_the_configs_goal_when_none_given(self) -> None:
        maximize_config = {
            "metric": {"name": "loss", "goal": "maximize"},
            "parameters": {},
        }
        api = MagicMock()
        api.sweep.return_value = make_scheduler_grid_sweep(config=maximize_config)
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.optuna.wandb_sweep",
                return_value="test_sweep",
            ),
            patch("wandb.sdk.sweeps.scheduler.optuna.Api", return_value=api),
        ):
            result = create_sweep_from_config(
                maximize_config, "test_entity", "test_project"
            )

        assert result._optimizer.study.direction == optuna.study.StudyDirection.MAXIMIZE

    def test_creates_multi_objective_study_from_metrics_when_none_given(self) -> None:
        metrics_config = {
            "metrics": [
                {"name": "loss", "goal": "minimize"},
                {"name": "accuracy", "goal": "maximize"},
            ],
            "parameters": {},
        }
        api = MagicMock()
        api.sweep.return_value = make_scheduler_grid_sweep(config=metrics_config)
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.optuna.wandb_sweep",
                return_value="test_sweep",
            ),
            patch("wandb.sdk.sweeps.scheduler.optuna.Api", return_value=api),
        ):
            result = create_sweep_from_config(
                metrics_config, "test_entity", "test_project"
            )

        assert [d.name.lower() for d in result._optimizer.study.directions] == [
            "minimize",
            "maximize",
        ]

    def test_uses_given_scheduler_options(
        self, study: optuna.Study, sweep: Sweep
    ) -> None:
        executor = MagicMock(spec=Executor)
        api = MagicMock()
        api.sweep.return_value = sweep
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.optuna.wandb_sweep",
                return_value="test_sweep",
            ),
            patch("wandb.sdk.sweeps.scheduler.optuna.Api", return_value=api),
        ):
            result = create_sweep_from_config(
                self.CONFIG,
                "test_entity",
                "test_project",
                options=OptunaOptions(
                    study=study,
                    poll_interval_s=2.5,
                    batch_size=7,
                    executor=executor,
                ),
            )

        assert result._poll_interval_s == 2.5
        assert result._batch_size == 7
        assert result._executor is executor

    def test_forwards_the_terminator_to_the_optimizer(
        self, study: optuna.Study, sweep: Sweep
    ) -> None:
        terminator = MagicMock()
        api = MagicMock()
        api.sweep.return_value = sweep
        with (
            patch(
                "wandb.sdk.sweeps.scheduler.optuna.wandb_sweep",
                return_value="test_sweep",
            ),
            patch("wandb.sdk.sweeps.scheduler.optuna.Api", return_value=api),
        ):
            result = create_sweep_from_config(
                self.CONFIG,
                "test_entity",
                "test_project",
                options=OptunaOptions(study=study, terminator=terminator),
            )

        assert result._optimizer._terminator is terminator
