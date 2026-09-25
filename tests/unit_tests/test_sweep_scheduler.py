"""Unit tests of Optimizer implementations, in pure Python.

No wandb-core process, IPC connection or backend is involved: each
Optimizer is exercised directly through its ask/tell interface. For the
Python-and-Go integration tests, see
tests/system_tests/test_sweep/test_sweep_scheduler_e2e.py.
"""

from __future__ import annotations

import abc
import dataclasses
import importlib.util
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler import client as scheduler_client
from wandb.sdk.sweeps.scheduler.optimizer import (
    Optimizer,
    Run,
    RunConfig,
    RunSuggestion,
    RunWithMetrics,
)
from wandb.sdk.sweeps.sweep_info import SweepInfo

HAS_AX = importlib.util.find_spec("ax") is not None
requires_ax = pytest.mark.skipif(
    not HAS_AX, reason="ax-platform requires Python >= 3.11"
)

SCHEDULER_GRID_SWEEP_CONFIG: dict[str, Any] = {
    "name": "test-sweep-grid-hyperband",
    "method": "grid",
    "early_terminate": {"type": "hyperband", "max_iter": 5, "eta": 2, "s": 2},
    "metric": {"name": "loss", "goal": "minimize"},
    "parameters": {"param1": {"values": [1, 2, 3]}},
}


def make_scheduler_grid_sweep(config: dict[str, Any] | None = None) -> SweepInfo:
    """Return the `SweepInfo` of a grid sweep with hyperband early termination.

    Args:
        config: An override for the sweep's config.
    """
    return SweepInfo(
        id="test_sweep",
        name="test_sweep",
        entity="test_entity",
        project="test_project",
        config=SCHEDULER_GRID_SWEEP_CONFIG if config is None else config,
    )


MULTI_OBJECTIVE_SWEEP_CONFIG: dict[str, Any] = {
    "metrics": [
        {"name": "loss", "goal": "minimize"},
        {"name": "accuracy", "goal": "maximize"},
    ],
    "parameters": {"x": {"min": 0.0, "max": 1.0}},
}


def make_run(
    suggestion: RunSuggestion,
    *,
    state: RunState,
    summary: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> RunWithMetrics:
    return RunWithMetrics(
        config=suggestion.config,
        state=state,
        wandb_run_id="wandb-run-id",
        summary_metrics=summary,
        history_metrics=history or [],
    )


def warm_start(
    optimizer: Optimizer,
    *,
    finished: Sequence[RunWithMetrics] = (),
    active: Sequence[Run] = (),
) -> dict[str, Any]:
    """Warm-start an optimizer from one page of a sweep's existing runs.

    Replays `SchedulerTaskExchange`'s warm-start task: every finished run is
    told first, then every active run is offered for adoption.

    Returns:
        The adopted runs, as W&B run id to optimizer run id.
    """
    for data in finished:
        optimizer.tell_existing_finished_run(data)
    adoptions: dict[str, Any] = {}
    for data in active:
        run_id = optimizer.tell_existing_active_run(data)
        if run_id is not None:
            adoptions[data.wandb_run_id] = str(run_id)
    return adoptions


class OptimizerAcceptanceTests(abc.ABC):
    """Contract tests every Optimizer implementation must satisfy."""

    @pytest.fixture
    def sweep(self) -> SweepInfo:
        return make_scheduler_grid_sweep()

    @abc.abstractmethod
    @pytest.fixture
    def optimizer(self, sweep: SweepInfo) -> Optimizer:
        """Return a fresh, configured Optimizer instance."""
        ...

    def test_next_2_runs_after_tell_1_run(
        self, optimizer: Optimizer, sweep: SweepInfo
    ) -> None:
        first_run = next(iter(optimizer.ask_n_runs(1)))
        run = make_run(first_run, state=RunState.FINISHED, summary={"loss": 1.0})
        optimizer.tell_run(first_run.run_id, run)
        suggestions = optimizer.ask_n_runs(2)
        assert len(suggestions) == 2
        assert all(isinstance(s, RunSuggestion) for s in suggestions)
        assert len({s.run_id for s in suggestions}) == 2  # unique ids
        assert suggestions[0].config["param1"].value == 2
        assert suggestions[1].config["param1"].value == 3

    def test_next_run_after_tell_existing_finished_run(
        self, optimizer: Optimizer, sweep: SweepInfo
    ) -> None:
        first_run = RunSuggestion(
            config=RunConfig.from_values({"param1": 1}), run_id="run_id"
        )
        run = make_run(first_run, state=RunState.FINISHED, summary={"loss": 1.0})
        optimizer.tell_existing_finished_run(run)
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        assert suggestion.config["param1"].value == 2

    def test_next_run_after_tell_existing_active_run(
        self, optimizer: Optimizer, sweep: SweepInfo
    ) -> None:
        first_run = RunSuggestion(
            config=RunConfig.from_values({"param1": 1}), run_id="run_id"
        )
        run = make_run(first_run, state=RunState.RUNNING, summary={"loss": 1.0})
        optimizer.tell_existing_active_run(run)
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        assert suggestion.config["param1"].value == 2

    def test_ids_unique_across_ask_and_adopt(self, optimizer: Optimizer) -> None:
        """Adoptions and suggestions must never share an id.

        The scheduler routes tells and prunes by id alone, so a collision
        would silently cross-wire two runs.
        """
        adopted = RunSuggestion(
            config=RunConfig.from_values({"param1": 1}), run_id="run_id"
        )
        run = make_run(adopted, state=RunState.RUNNING, summary={})
        adopted_id = optimizer.tell_existing_active_run(run)
        suggestions = optimizer.ask_n_runs(2)
        ids = [s.run_id for s in suggestions]
        if adopted_id is not None:
            ids.append(adopted_id)
        assert len(set(ids)) == len(ids)

    def test_forget_run_then_ask_still_works(self, optimizer: Optimizer) -> None:
        """Forgetting a suggestion must not corrupt the search state."""
        first_run = next(iter(optimizer.ask_n_runs(1)))
        optimizer.forget_run(first_run.run_id)
        suggestions = optimizer.ask_n_runs(1)
        assert suggestions is None or len(suggestions) <= 1

    def test_prune_runs_returns_empty_for_no_candidates(
        self, optimizer: Optimizer
    ) -> None:
        assert optimizer.prune_runs([], []) == []

    # The better running run's final loss. Low enough that the pruner
    # under test spares that run; subclasses lower it for stricter
    # pruners.
    better_running_loss = 7.0

    def start_runs_to_prune(
        self, optimizer: Optimizer
    ) -> tuple[list[RunSuggestion], list[RunWithMetrics]]:
        """Finish one run and return two running candidates, worst first."""
        suggestions = optimizer.ask_n_runs(3)
        assert len(suggestions) == 3

        optimizer.tell_run(
            suggestions[0].run_id,
            make_run(
                suggestions[0],
                state=RunState.FINISHED,
                summary={"loss": 6.0},
                history=[
                    {"loss": 10.0, "_step": 0},
                    {"loss": 6.0, "_step": 1},
                    {"loss": 6.0, "_step": 2},
                ],
            ),
        )
        worst_running = make_run(
            suggestions[1],
            state=RunState.RUNNING,
            summary={"loss": 10.0},
            history=[{"loss": 10.0, "_step": 0}, {"loss": 10.0, "_step": 1}],
        )
        loss = self.better_running_loss
        better_running = make_run(
            suggestions[2],
            state=RunState.RUNNING,
            summary={"loss": loss},
            history=[
                {"loss": 10.0, "_step": 0},
                {"loss": loss, "_step": 1},
                {"loss": loss, "_step": 2},
            ],
        )
        optimizer.tell_run(suggestions[1].run_id, worst_running)
        optimizer.tell_run(suggestions[2].run_id, better_running)
        return suggestions[1:], [worst_running, better_running]

    def prune(
        self,
        optimizer: Optimizer,
        run_ids: Sequence[str],
        runs: Sequence[RunWithMetrics],
    ) -> Sequence[str]:
        """Prune `runs`; a subclass may stub a statistical pruner's verdict."""
        return optimizer.prune_runs(run_ids, runs)

    def test_prune_runs_stops_worst_running_run(self, optimizer: Optimizer) -> None:
        candidates, runs = self.start_runs_to_prune(optimizer)
        run_ids = [candidate.run_id for candidate in candidates]

        assert self.prune(optimizer, run_ids, runs) == [run_ids[0]]

    def test_a_pruned_run_is_final(self, optimizer: Optimizer) -> None:
        """Pruning finalizes the run, so later updates must not revive it.

        The scheduler keeps reporting a pruned run until its stop goes
        through, and never offers it for pruning again.
        """
        candidates, runs = self.start_runs_to_prune(optimizer)
        pruned_id = candidates[0].run_id
        assert self.prune(optimizer, [c.run_id for c in candidates], runs) == [
            pruned_id
        ]

        # Its stop failed, so it is still reported as running.
        optimizer.tell_run(pruned_id, runs[0])

        assert self.prune(optimizer, [pruned_id], [runs[0]]) == []


class MultiObjectiveOptimizerAcceptanceTests(abc.ABC):
    """Contract tests every Optimizer that accepts `metrics` must satisfy.

    A multi-objective sweep declares a goal per metric, so a run's result
    counts only once every objective is in, and no pruner ranking a single
    value can judge the runs producing them.
    """

    RESULT = {"loss": 0.25, "accuracy": 0.9}

    @pytest.fixture
    def sweep(self) -> SweepInfo:
        return make_scheduler_grid_sweep(config=MULTI_OBJECTIVE_SWEEP_CONFIG)

    @abc.abstractmethod
    @pytest.fixture
    def optimizer(self, sweep: SweepInfo) -> Optimizer:
        """Return an Optimizer searching `sweep`'s two objectives."""
        ...

    @abc.abstractmethod
    def recorded_objectives(self, optimizer: Optimizer) -> list[list[Any] | None]:
        """Return the objective values of each result the optimizer recorded.

        Ordered as recorded, with None for a run it declined to score.

        Args:
            optimizer: The optimizer under test.
        """
        ...

    def finish(
        self, optimizer: Optimizer, suggestion: RunSuggestion, summary: dict[str, Any]
    ) -> None:
        optimizer.tell_run(
            suggestion.run_id,
            make_run(suggestion, state=RunState.FINISHED, summary=summary),
        )

    @pytest.mark.parametrize(
        ("summary", "recorded"),
        [
            ({"loss": 0.25, "accuracy": 0.9}, [[0.25, 0.9]]),
            ({"loss": 0.25}, [None]),
        ],
        ids=["every_objective", "missing_an_objective"],
    )
    def test_a_result_counts_only_with_every_objective(
        self,
        optimizer: Optimizer,
        summary: dict[str, Any],
        recorded: list[list[Any] | None],
    ) -> None:
        suggestion = next(iter(optimizer.ask_n_runs(1)))

        self.finish(optimizer, suggestion, summary)

        assert self.recorded_objectives(optimizer) == recorded

    def test_the_search_continues_after_a_result(self, optimizer: Optimizer) -> None:
        """Nothing is left in flight, so the next ask must propose a run."""
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        self.finish(optimizer, suggestion, self.RESULT)

        assert optimizer.ask_n_runs(1)

    def test_warm_start_records_every_objective(self, optimizer: Optimizer) -> None:
        existing = RunSuggestion(
            config=RunConfig.from_values({"x": 0.25}), run_id="prior"
        )

        optimizer.tell_existing_finished_run(
            make_run(existing, state=RunState.FINISHED, summary=self.RESULT)
        )

        assert self.recorded_objectives(optimizer) == [[0.25, 0.9]]

    def test_pruning_never_stops_a_run(self, optimizer: Optimizer) -> None:
        """Pruners rank one value, so they cannot judge a Pareto front."""
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        run = make_run(
            suggestion,
            state=RunState.RUNNING,
            summary={"loss": 9.0, "accuracy": 0.1},
            history=[{"loss": 9.0, "accuracy": 0.1, "_step": 0}],
        )
        optimizer.tell_run(suggestion.run_id, run)

        assert optimizer.prune_runs([suggestion.run_id], [run]) == []


class TestObjectiveMetrics:
    """The base Optimizer reads its objectives from `metric` or `metrics`."""

    def make_optimizer(self, config: dict[str, Any]) -> Optimizer:
        from wandb.sdk.sweeps.scheduler.wandb import WandbOptimizer

        return WandbOptimizer(sweep=make_scheduler_grid_sweep(config=config))

    @pytest.mark.parametrize(
        ("config", "names", "goals"),
        [
            (SCHEDULER_GRID_SWEEP_CONFIG, ["loss"], ["minimize"]),
            (
                MULTI_OBJECTIVE_SWEEP_CONFIG,
                ["loss", "accuracy"],
                ["minimize", "maximize"],
            ),
        ],
        ids=["metric", "metrics"],
    )
    def test_names_and_goals_keep_the_declaration_order(
        self, config: dict[str, Any], names: list[str], goals: list[str]
    ) -> None:
        optimizer = self.make_optimizer(config)

        assert optimizer.metric_names() == names
        assert optimizer.metric_goals() == goals

    @pytest.mark.parametrize(
        ("summary", "values"),
        [
            ({"loss": 1.0, "accuracy": 0.5}, [1.0, 0.5]),
            ({"loss": 1.0}, None),
            ({}, None),
        ],
        ids=["every_objective", "missing_an_objective", "nothing_logged"],
    )
    def test_objective_values_needs_every_objective(
        self, summary: dict[str, Any], values: list[Any] | None
    ) -> None:
        optimizer = self.make_optimizer(MULTI_OBJECTIVE_SWEEP_CONFIG)

        assert optimizer.objective_values(summary) == values


class TestSweepSchedulerCli:
    """Tests for the `wandb sweep-scheduler` command's option handling."""

    @pytest.fixture
    def run_scheduler_mock(self, monkeypatch):
        from unittest.mock import MagicMock

        from wandb.proto import wandb_sweep_scheduler_pb2 as sspb
        from wandb.sdk.sweeps.scheduler import client

        mock = MagicMock(
            return_value=(
                sspb.SweepSchedulerServerDoneTask(
                    reason=sspb.SweepSchedulerServerDoneTask.REASON_SWEEP_FINISHED
                ),
                False,
            )
        )
        monkeypatch.setattr(client, "run_scheduler", mock)
        return mock

    @pytest.fixture
    def api(self, monkeypatch):
        """An API with no default entity or project of its own."""
        from unittest.mock import MagicMock

        import wandb

        api = MagicMock()
        api.settings = {"entity": None, "project": None}
        monkeypatch.setattr(wandb, "Api", lambda *a, **k: api)
        return api

    def invoke(self, *args: str):
        from click.testing import CliRunner
        from wandb.cli import cli

        return CliRunner().invoke(cli.sweep_scheduler, args, catch_exceptions=False)

    @pytest.mark.parametrize(
        ("argv", "expected_error"),
        [
            (("--batch-size", "0", "e/p/s"), "--batch-size must be at least 1"),
            # A bad sweep path must fail loudly, like the other validations.
            (("a/b/c/d",), "Expected sweep_id in form of"),
            (("bare-sweep-id",), "--entity and --project"),
        ],
        ids=["nonpositive_batch_size", "malformed_sweep_id", "no_entity_or_project"],
    )
    def test_bad_arguments_are_rejected(
        self, api, run_scheduler_mock, argv, expected_error
    ):
        result = self.invoke(*argv)

        assert result.exit_code == 1
        assert expected_error in result.output
        run_scheduler_mock.assert_not_called()

    def test_forwards_options_to_host(self, api, run_scheduler_mock):
        result = self.invoke("--batch-size", "4", "--poll-interval", "7", "e/p/s")

        assert result.exit_code == 0
        kwargs = run_scheduler_mock.call_args.kwargs
        assert kwargs["entity"] == "e"
        assert kwargs["project"] == "p"
        assert kwargs["sweep_id"] == "s"
        assert kwargs["batch_size"] == 4
        assert kwargs["poll_interval"] == 7.0

    def test_wandb_engine_builds_wandb_optimizer(self, api, run_scheduler_mock):
        from wandb.sdk.sweeps.scheduler.wandb import WandbOptimizer

        result = self.invoke("e/p/s")
        assert result.exit_code == 0

        make_optimizer = run_scheduler_mock.call_args.kwargs["make_optimizer"]
        wandb_engine = SweepInfo(
            id="s",
            name="s",
            entity="e",
            project="p",
            config={
                **SCHEDULER_GRID_SWEEP_CONFIG,
                "scheduler": {"engine": "wandb"},
            },
        )
        optimizer = make_optimizer(wandb_engine)
        assert isinstance(optimizer, WandbOptimizer)

    @pytest.mark.parametrize(
        ("config", "expected_error"),
        [
            ({}, "Unsupported engine: None"),
            ({"scheduler": {"engine": "genetic"}}, "Unsupported engine: genetic"),
        ],
        ids=["no_engine", "unknown_engine"],
    )
    def test_unsupported_engine_rejected(
        self, api, run_scheduler_mock, config, expected_error
    ):
        result = self.invoke("e/p/s")
        assert result.exit_code == 0

        make_optimizer = run_scheduler_mock.call_args.kwargs["make_optimizer"]
        sweep = SweepInfo(id="s", name="s", entity="e", project="p", config=config)
        with pytest.raises(Exception, match=expected_error):
            make_optimizer(sweep)

    def test_scheduler_failure_exits_nonzero(self, api, run_scheduler_mock):
        import wandb

        run_scheduler_mock.side_effect = wandb.Error("the sweep was deleted")

        result = self.invoke("e/p/s")

        assert result.exit_code == 1


class TestWandbOptimizerAcceptance(OptimizerAcceptanceTests):
    @pytest.fixture
    def optimizer(self, sweep: SweepInfo) -> Optimizer:
        from wandb.sdk.sweeps.scheduler.wandb import WandbOptimizer

        return WandbOptimizer(sweep=sweep)

    def test_forget_run_reproposes_grid_point(self, optimizer: Optimizer) -> None:
        """Forgetting deletes the sample, so grid offers the point again."""
        first_run = next(iter(optimizer.ask_n_runs(1)))
        first_value = first_run.config["param1"].value
        optimizer.forget_run(first_run.run_id)
        again = next(iter(optimizer.ask_n_runs(1)))
        assert again.config["param1"].value == first_value


class TestRunSchedulerInit:
    def test_server_response_error_becomes_wandb_error(self, monkeypatch):
        """A raw ServerResponseError must not escape `run_scheduler`.

        The CLI only knows to report `wandb.Error` failures cleanly, so
        errors from wandb-core's init round trip must be wrapped.
        """
        from unittest.mock import MagicMock

        import wandb
        from wandb.sdk.mailbox.mailbox_handle import ServerResponseError
        from wandb.sdk.sweeps.scheduler import client

        monkeypatch.setattr(
            client.wbauth, "authenticate_session", lambda **kwargs: True
        )

        singleton = MagicMock()
        singleton.asyncer.run.side_effect = ServerResponseError("sweep not found")
        monkeypatch.setattr(client.wandb_setup, "singleton", lambda: singleton)

        with pytest.raises(wandb.Error, match="failed to initialize"):
            client.run_scheduler(
                entity="e",
                project="p",
                sweep_id="s",
                make_optimizer=lambda sweep: None,
                batch_size=1,
                poll_interval=10,
            )


class TestSchedulerHostOffMainThread:
    def test_sigint_handler_is_optional(self) -> None:
        """The host must work off the main thread, where signal cannot.

        Only the main thread may install a signal handler, and
        `run_scheduler` is an ordinary function a caller may run in a
        worker.
        """
        import concurrent.futures

        from wandb.sdk.sweeps.scheduler.client import _install_sigint_handler

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            handler = pool.submit(
                _install_sigint_handler, None, None, "scheduler-0"
            ).result()

        assert handler is None


def _make_sequential_sampler(optuna_module: Any) -> Any:
    """A deterministic sampler cycling a categorical param's choices in order.

    Real optuna samplers pick randomly (or per some search strategy), but the
    shared acceptance tests -- written against `WandbOptimizer`'s
    deterministic grid search -- assert an exact suggestion order.
    """

    class _SequentialSampler(optuna_module.samplers.BaseSampler):
        def infer_relative_search_space(self, study: Any, trial: Any) -> dict:
            return {}

        def sample_relative(self, study: Any, trial: Any, search_space: dict) -> dict:
            return {}

        def sample_independent(
            self, study: Any, trial: Any, param_name: str, param_distribution: Any
        ) -> Any:
            choices = list(param_distribution.choices)
            seen = sum(
                1
                for t in study.get_trials(deepcopy=False)
                if t.number != trial.number and param_name in t.params
            )
            return choices[seen % len(choices)]

    return _SequentialSampler()


class OptunaOptimizerAcceptanceTests(OptimizerAcceptanceTests):
    """Shared setup for the Optuna optimizer flavors."""

    # optuna's MedianPruner judges a running trial against the completed
    # trials' median (6.0 here) rather than ranking running trials
    # against each other, so the kept run's loss must sit below it.
    better_running_loss = 5.0

    @pytest.fixture
    def study(self) -> Any:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        return optuna.create_study(
            direction="minimize",
            sampler=_make_sequential_sampler(optuna),
            pruner=optuna.pruners.MedianPruner(n_startup_trials=0, n_warmup_steps=0),
        )


class TestOptunaDeclarativeOptimizerAcceptance(OptunaOptimizerAcceptanceTests):
    @pytest.fixture
    def optimizer(self, study: Any, sweep: SweepInfo) -> Optimizer:
        import optuna
        from wandb.sdk.sweeps.scheduler.optuna import OptunaDeclarativeOptimizer

        distributions = {
            "param1": optuna.distributions.CategoricalDistribution([1, 2, 3])
        }
        return OptunaDeclarativeOptimizer(study, distributions, sweep)


class TestOptunaImperativeOptimizerAcceptance(OptunaOptimizerAcceptanceTests):
    @pytest.fixture
    def optimizer(self, study: Any, sweep: SweepInfo) -> Optimizer:
        from wandb.sdk.sweeps.scheduler.optuna import OptunaImperativeOptimizer

        def trial_constructor(trial: Any) -> dict[str, Any]:
            return {"param1": trial.suggest_categorical("param1", [1, 2, 3])}

        return OptunaImperativeOptimizer(study, trial_constructor, sweep)


class TestOptunaMultiObjectiveAcceptance(MultiObjectiveOptimizerAcceptanceTests):
    @pytest.fixture
    def optimizer(self, sweep: SweepInfo) -> Optimizer:
        import optuna
        from wandb.sdk.sweeps.scheduler.optuna import (
            OptunaDeclarativeOptimizer,
            create_study_from_sweep_config,
        )

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = create_study_from_sweep_config(MULTI_OBJECTIVE_SWEEP_CONFIG)
        distributions = {"x": optuna.distributions.FloatDistribution(0.0, 1.0)}
        return OptunaDeclarativeOptimizer(study, distributions, sweep)

    def recorded_objectives(self, optimizer: Optimizer) -> list[list[Any] | None]:
        """A trial optuna was told nothing for has no values of its own."""
        return [
            list(trial.values) if trial.values is not None else None
            for trial in optimizer.study.get_trials(deepcopy=False)
        ]


class TerminatorContractTests(abc.ABC):
    """`should_terminate_sweep` must delegate to the caller's terminator."""

    @abc.abstractmethod
    def make_optimizer(self, terminator: Any = None) -> tuple[Optimizer, Any]:
        """Build an optimizer with `terminator`.

        Returns:
            The optimizer and the argument its terminator is called with.
        """
        ...

    def test_no_terminator_never_terminates(self) -> None:
        optimizer, _ = self.make_optimizer()
        assert optimizer.should_terminate_sweep() is False

    @pytest.mark.parametrize("verdict", [True, False])
    def test_delegates_to_the_configured_terminator(self, verdict: bool) -> None:
        from unittest.mock import MagicMock

        terminator = MagicMock(return_value=verdict)
        optimizer, callback_arg = self.make_optimizer(terminator)

        assert optimizer.should_terminate_sweep() is verdict
        terminator.assert_called_once_with(callback_arg)


class TestOptunaOptimizerTermination(TerminatorContractTests):
    def make_optimizer(self, terminator: Any = None) -> tuple[Optimizer, Any]:
        import optuna
        from wandb.sdk.sweeps.scheduler.optuna import OptunaDeclarativeOptimizer

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction="minimize")
        distributions = {"param1": optuna.distributions.IntDistribution(1, 3)}
        optimizer = OptunaDeclarativeOptimizer(
            study, distributions, make_scheduler_grid_sweep(), terminator
        )
        return optimizer, study


def _sequential_ax_generation_strategy(param_name: str, values: list[Any]) -> Any:
    """A deterministic generation strategy cycling a choice param's values.

    Ax's real generation strategies pick via Sobol/BoTorch, which the shared
    acceptance tests -- written against `WandbOptimizer`'s deterministic grid
    search -- don't assume.
    """
    from ax.generation_strategy.external_generation_node import ExternalGenerationNode
    from ax.generation_strategy.generation_strategy import GenerationStrategy

    class _SequentialNode(ExternalGenerationNode):
        def __init__(self) -> None:
            super().__init__(name="Sequential", should_deduplicate=False)
            self._next_index = 0

        def update_generator_state(self, experiment: Any, data: Any) -> None:
            self._next_index = len(experiment.trials)

        def get_next_candidate(self, pending_parameters: list[Any]) -> dict[str, Any]:
            value = values[self._next_index % len(values)]
            self._next_index += 1
            return {param_name: value}

    return GenerationStrategy(name="Sequential", nodes=[_SequentialNode()])


@requires_ax
class TestAxOptimizerAcceptance(OptimizerAcceptanceTests):
    """Ax has a single optimizer flavor -- no define-by-run counterpart."""

    @pytest.fixture
    def optimizer(self, sweep: SweepInfo) -> Optimizer:
        from wandb.sdk.sweeps.scheduler.ax import AxOptimizer, create_default_client

        client = create_default_client(SCHEDULER_GRID_SWEEP_CONFIG)
        client.set_generation_strategy(
            _sequential_ax_generation_strategy("param1", [1, 2, 3])
        )
        return AxOptimizer(client, sweep)

    def prune(
        self,
        optimizer: Optimizer,
        run_ids: Sequence[str],
        runs: Sequence[RunWithMetrics],
    ) -> Sequence[str]:
        """Stub Ax's statistical early-stopping verdict to flag run one."""
        with patch.object(
            optimizer.client,
            "should_stop_trial_early",
            side_effect=lambda trial_index: trial_index == int(run_ids[0]),
        ):
            return optimizer.prune_runs(run_ids, runs)


@requires_ax
class TestAxMultiObjectiveAcceptance(MultiObjectiveOptimizerAcceptanceTests):
    @pytest.fixture
    def optimizer(self, sweep: SweepInfo) -> Optimizer:
        from wandb.sdk.sweeps.scheduler.ax import AxOptimizer, create_default_client

        return AxOptimizer(create_default_client(MULTI_OBJECTIVE_SWEEP_CONFIG), sweep)

    def recorded_objectives(self, optimizer: Optimizer) -> list[list[Any] | None]:
        """Ax scores a completed trial only; a failed one holds no result."""
        from wandb.sdk.sweeps.scheduler.ax import _experiment

        experiment = _experiment(optimizer.client)
        data = experiment.lookup_data().df
        recorded: list[list[Any] | None] = []
        for trial_index, trial in sorted(experiment.trials.items()):
            if not trial.status.is_completed:
                recorded.append(None)
                continue
            rows = data[data["trial_index"] == trial_index]
            recorded.append(
                [
                    rows[rows["metric_name"] == name]["mean"].iloc[-1]
                    for name in optimizer.metric_names()
                ]
            )
        return recorded


@requires_ax
class TestAxOptimizerTermination(TerminatorContractTests):
    def make_optimizer(self, terminator: Any = None) -> tuple[Optimizer, Any]:
        from wandb.sdk.sweeps.scheduler.ax import AxOptimizer, create_default_client

        client = create_default_client(SCHEDULER_GRID_SWEEP_CONFIG)
        return AxOptimizer(client, make_scheduler_grid_sweep(), terminator), client


RESUMABLE_SWEEP_CONFIG: dict[str, Any] = {
    "metric": {"name": "loss", "goal": "minimize"},
    "parameters": {"x": {"min": 0.0, "max": 1.0}},
}


class ResumableOptimizerAcceptanceTests(abc.ABC):
    """Warm start resumes the trials a reloaded backend already holds.

    Each test drives one optimizer, then rebuilds a second on the backend's
    state reloaded from storage, as a restarted scheduler would.
    """

    @pytest.fixture
    def sweep(self) -> SweepInfo:
        return make_scheduler_grid_sweep(config=RESUMABLE_SWEEP_CONFIG)

    @abc.abstractmethod
    @pytest.fixture
    def optimizer(self, sweep: SweepInfo) -> Optimizer:
        """Return a fresh optimizer over `RESUMABLE_SWEEP_CONFIG`'s space."""
        ...

    @abc.abstractmethod
    @pytest.fixture
    def reload(self, sweep: SweepInfo) -> Callable[[Optimizer], Optimizer]:
        """Return a callable rebuilding an optimizer from its stored state."""
        ...

    @abc.abstractmethod
    def completed(self, optimizer: Optimizer) -> list[bool]:
        """Return whether each of the backend's trials is complete."""
        ...

    @abc.abstractmethod
    def add_foreign_running_trial(
        self, optimizer: Optimizer, params: dict[str, Any]
    ) -> str:
        """Start a trial the sweep never asked for; return its run id."""
        ...

    @abc.abstractmethod
    def trials_class(self) -> type:
        """Return the class adapting the backend's trials for a resumer."""
        ...

    @pytest.fixture
    def listed(self):
        """Spy on the resumer listing every trial the backend holds."""
        trials_class = self.trials_class()
        with patch.object(
            trials_class,
            "existing",
            autospec=True,
            side_effect=trials_class.existing,
        ) as existing:
            yield existing

    def test_the_backend_is_listed_once_and_only_by_warm_start(
        self, optimizer: Optimizer, reload, listed
    ) -> None:
        """A large backend is not listed for a sweep with nothing to resume."""
        suggestions = optimizer.ask_n_runs(2)
        runs = [
            dataclasses.replace(
                make_run(suggestion, state=RunState.RUNNING, summary={}),
                wandb_run_id=f"run-{i}",
            )
            for i, suggestion in enumerate(suggestions)
        ]
        for suggestion, run in zip(suggestions, runs, strict=True):
            optimizer.tell_run(suggestion.run_id, run)

        second = reload(optimizer)
        assert listed.call_count == 0

        warm_start(second, active=runs)
        assert listed.call_count == 1

    def test_a_warm_start_after_generation_does_not_list_the_backend(
        self, optimizer: Optimizer, listed
    ) -> None:
        suggestion = next(iter(optimizer.ask_n_runs(1)))

        warm_start(
            optimizer,
            active=[make_run(suggestion, state=RunState.RUNNING, summary={})],
        )

        assert listed.call_count == 0

    def test_a_recorded_finished_run_is_not_added_again(
        self, optimizer: Optimizer, reload
    ) -> None:
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        finished = make_run(suggestion, state=RunState.FINISHED, summary={"loss": 1.0})
        optimizer.tell_run(suggestion.run_id, finished)

        second = reload(optimizer)
        warm_start(second, finished=[finished])

        assert self.completed(second) == [True]

    def test_a_warm_started_run_is_not_added_again(
        self, optimizer: Optimizer, reload
    ) -> None:
        suggestion = RunSuggestion(
            config=RunConfig.from_values({"x": 0.5}), run_id="unused"
        )
        finished = make_run(suggestion, state=RunState.FINISHED, summary={"loss": 1.0})
        warm_start(optimizer, finished=[finished])

        second = reload(optimizer)
        warm_start(second, finished=[finished])

        assert self.completed(second) == [True]

    def test_an_active_run_resumes_its_running_trial(
        self, optimizer: Optimizer, reload
    ) -> None:
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        running = make_run(
            suggestion,
            state=RunState.RUNNING,
            summary={},
            history=[{"loss": 3.0, "_step": 0}],
        )
        optimizer.tell_run(suggestion.run_id, running)

        second = reload(optimizer)
        adoptions = warm_start(second, active=[running])
        second.tell_run(
            adoptions[running.wandb_run_id],
            make_run(suggestion, state=RunState.FINISHED, summary={"loss": 2.0}),
        )

        assert adoptions == {running.wandb_run_id: suggestion.run_id}
        assert self.completed(second) == [True]

    def test_an_unpolled_trial_is_matched_to_its_run_by_params(
        self, optimizer: Optimizer, reload
    ) -> None:
        """A scheduler that stopped before the first poll never saw the run id."""
        suggestion = next(iter(optimizer.ask_n_runs(1)))

        second = reload(optimizer)
        running = make_run(suggestion, state=RunState.RUNNING, summary={})
        adoptions = warm_start(second, active=[running])

        assert adoptions == {running.wandb_run_id: suggestion.run_id}
        assert self.completed(second) == [False]

    def test_a_run_that_finished_unwatched_completes_its_trial(
        self, optimizer: Optimizer, reload
    ) -> None:
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        optimizer.tell_run(
            suggestion.run_id,
            make_run(suggestion, state=RunState.RUNNING, summary={}),
        )

        second = reload(optimizer)
        warm_start(
            second,
            finished=[
                make_run(suggestion, state=RunState.FINISHED, summary={"loss": 2.0})
            ],
        )

        assert self.completed(second) == [True]

    def test_an_active_run_whose_trial_finished_is_not_adopted(
        self, optimizer: Optimizer, reload
    ) -> None:
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        running = make_run(suggestion, state=RunState.RUNNING, summary={})
        optimizer.tell_run(suggestion.run_id, running)
        optimizer.forget_run(suggestion.run_id)

        second = reload(optimizer)

        assert warm_start(second, active=[running]) == {}
        assert self.completed(second) == [False]

    def test_another_sources_running_trial_is_not_adopted(
        self, optimizer: Optimizer, reload
    ) -> None:
        foreign_id = self.add_foreign_running_trial(optimizer, {"x": 0.5})

        second = reload(optimizer)
        running = make_run(
            RunSuggestion(config=RunConfig.from_values({"x": 0.5}), run_id=""),
            state=RunState.RUNNING,
            summary={},
        )
        adoptions = warm_start(second, active=[running])

        assert adoptions[running.wandb_run_id] != foreign_id


class OptunaResumableAcceptanceTests(ResumableOptimizerAcceptanceTests):
    """Stores the study in an optuna journal file, reloaded by study name."""

    @pytest.fixture
    def storage_path(self, tmp_path) -> str:
        return str(tmp_path / "journal.log")

    def load_study(self, storage_path: str) -> Any:
        import optuna
        from optuna.storages.journal import JournalFileBackend, JournalStorage

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        storage = JournalStorage(JournalFileBackend(storage_path))
        return optuna.create_study(
            study_name="study",
            storage=storage,
            direction="minimize",
            load_if_exists=True,
        )

    @abc.abstractmethod
    def make_optimizer(self, study: Any, sweep: SweepInfo) -> Optimizer:
        """Build this flavor's optimizer on `study`."""
        ...

    @pytest.fixture
    def optimizer(self, sweep: SweepInfo, storage_path: str) -> Optimizer:
        return self.make_optimizer(self.load_study(storage_path), sweep)

    @pytest.fixture
    def reload(self, sweep: SweepInfo, storage_path: str):
        return lambda _: self.make_optimizer(self.load_study(storage_path), sweep)

    def completed(self, optimizer: Optimizer) -> list[bool]:
        import optuna

        return [
            trial.state == optuna.trial.TrialState.COMPLETE
            for trial in optimizer.study.get_trials(deepcopy=False)
        ]

    def add_foreign_running_trial(
        self, optimizer: Optimizer, params: dict[str, Any]
    ) -> str:
        import optuna

        optimizer.study.enqueue_trial(params)
        trial = optimizer.study.ask(
            {"x": optuna.distributions.FloatDistribution(0.0, 1.0)}
        )
        return str(trial.number)

    def trials_class(self) -> type:
        from wandb.sdk.sweeps.scheduler.optuna import _StudyTrials

        return _StudyTrials

    def test_a_resumed_trial_keeps_its_reported_values(
        self, optimizer: Optimizer, reload
    ) -> None:
        """A step reported before the restart is not reported again."""
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        history = [{"loss": 3.0, "_step": 0}]
        running = make_run(
            suggestion, state=RunState.RUNNING, summary={}, history=history
        )
        optimizer.tell_run(suggestion.run_id, running)

        second = reload(optimizer)
        adoptions = warm_start(second, active=[running])
        second.tell_run(
            adoptions[running.wandb_run_id],
            make_run(
                suggestion,
                state=RunState.FINISHED,
                summary={"loss": 2.0},
                history=[*history, {"loss": 2.0, "_step": 1}],
            ),
        )

        (trial,) = second.study.get_trials(deepcopy=False)
        assert trial.value == 2.0
        assert trial.intermediate_values == {0: 3.0, 1: 2.0}

    def test_an_in_memory_study_is_neither_labeled_nor_listed(
        self, sweep: SweepInfo, listed
    ) -> None:
        """An in-memory study can't be reloaded, so there is nothing to resume."""
        import optuna

        study = optuna.create_study(direction="minimize")
        first = self.make_optimizer(study, sweep)
        suggestion = next(iter(first.ask_n_runs(1)))
        running = make_run(suggestion, state=RunState.RUNNING, summary={})
        first.tell_run(suggestion.run_id, running)

        warm_start(self.make_optimizer(study, sweep), active=[running])

        assert listed.call_count == 0
        assert [t.user_attrs for t in study.get_trials(deepcopy=False)] == [{}, {}]


class TestOptunaDeclarativeResumableAcceptance(OptunaResumableAcceptanceTests):
    def make_optimizer(self, study: Any, sweep: SweepInfo) -> Optimizer:
        import optuna
        from wandb.sdk.sweeps.scheduler.optuna import OptunaDeclarativeOptimizer

        distributions = {"x": optuna.distributions.FloatDistribution(0.0, 1.0)}
        return OptunaDeclarativeOptimizer(study, distributions, sweep)


class TestOptunaImperativeResumableAcceptance(OptunaResumableAcceptanceTests):
    def make_optimizer(self, study: Any, sweep: SweepInfo) -> Optimizer:
        from wandb.sdk.sweeps.scheduler.optuna import OptunaImperativeOptimizer

        return OptunaImperativeOptimizer(
            study, lambda trial: {"x": trial.suggest_float("x", 0.0, 1.0)}, sweep
        )


@requires_ax
class TestAxResumableAcceptance(ResumableOptimizerAcceptanceTests):
    """Saves the client to a JSON file, reloaded with `load_from_json_file`."""

    @pytest.fixture
    def optimizer(self, sweep: SweepInfo) -> Optimizer:
        from wandb.sdk.sweeps.scheduler.ax import AxOptimizer, create_default_client

        return AxOptimizer(create_default_client(RESUMABLE_SWEEP_CONFIG), sweep)

    @pytest.fixture
    def reload(self, sweep: SweepInfo, tmp_path):
        from ax.api.client import Client
        from wandb.sdk.sweeps.scheduler.ax import AxOptimizer

        path = str(tmp_path / "client.json")

        def reload(optimizer: Optimizer) -> Optimizer:
            optimizer.client.save_to_json_file(path)
            return AxOptimizer(Client.load_from_json_file(path), sweep)

        return reload

    def completed(self, optimizer: Optimizer) -> list[bool]:
        from wandb.sdk.sweeps.scheduler.ax import _experiment

        return [
            trial.status.is_completed
            for _, trial in sorted(_experiment(optimizer.client).trials.items())
        ]

    def add_foreign_running_trial(
        self, optimizer: Optimizer, params: dict[str, Any]
    ) -> str:
        return str(optimizer.client.attach_trial(parameters=params))

    def trials_class(self) -> type:
        from wandb.sdk.sweeps.scheduler.ax import _ExperimentTrials

        return _ExperimentTrials
class TestLoadSourceObject:
    def test_loads_named_function(self, tmp_path: Path) -> None:
        source = tmp_path / "source.py"
        source.write_text("def configure():\n    return 42\n", encoding="utf-8")

        loaded = scheduler_client.load_source_object(str(source), "configure")

        assert loaded() == 42

    def test_empty_source_raises(self) -> None:
        with pytest.raises(ValueError, match="scheduler.source.*'configure'"):
            scheduler_client.load_source_object("", "configure")

    def test_missing_attribute_raises(self, tmp_path: Path) -> None:
        source = tmp_path / "source.py"
        source.write_text("OTHER = 1\n", encoding="utf-8")

        with pytest.raises(ValueError, match="has no attribute 'configure'"):
            scheduler_client.load_source_object(str(source), "configure")


class TestLoadOptimizerConfig:
    def test_returns_bare_optimizer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        optimizer = object()
        configure = MagicMock(return_value=optimizer)
        monkeypatch.setattr(
            scheduler_client, "load_source_object", lambda *_: configure
        )

        loaded, terminator = scheduler_client.load_optimizer_config(
            "optimizer.py", "configure", "engine.Optimizer"
        )

        assert loaded is optimizer
        assert terminator is None

    def test_returns_optimizer_and_terminator(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        optimizer = object()
        terminator = MagicMock(return_value=True)
        configure = MagicMock(return_value=(optimizer, terminator))
        monkeypatch.setattr(
            scheduler_client, "load_source_object", lambda *_: configure
        )

        loaded, loaded_terminator = scheduler_client.load_optimizer_config(
            "optimizer.py", "configure", "engine.Optimizer"
        )

        assert loaded is optimizer
        assert loaded_terminator is terminator

    def test_returns_only_optimizer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        optimizer = object()
        configure = MagicMock(return_value=(optimizer, None))
        monkeypatch.setattr(
            scheduler_client, "load_source_object", lambda *_: configure
        )

        loaded, terminator = scheduler_client.load_optimizer_config(
            "optimizer.py", "configure", "engine.Optimizer"
        )

        assert loaded is optimizer
        assert terminator is None

    def test_non_callable_terminator_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        configure = MagicMock(return_value=(object(), "not-callable"))
        monkeypatch.setattr(
            scheduler_client, "load_source_object", lambda *_: configure
        )

        with pytest.raises(ValueError, match="terminator.*Callable"):
            scheduler_client.load_optimizer_config(
                "optimizer.py", "configure", "engine.Optimizer"
            )
