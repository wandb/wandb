"""Unit tests of Optimizer implementations, in pure Python.

No wandb-core process, IPC connection or backend is involved: each
Optimizer is exercised directly through its ask/tell interface. For the
Python-and-Go integration tests, see
tests/system_tests/test_sweep/test_sweep_scheduler_e2e.py.
"""

from __future__ import annotations

import abc
from typing import Any

import pytest
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.optimizer import (
    Optimizer,
    RunConfig,
    RunSuggestion,
    RunWithMetrics,
)
from wandb.sdk.sweeps.sweep_info import SweepInfo

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

    def test_prune_runs_hyperband_stops_worst_running_run(
        self, optimizer: Optimizer
    ) -> None:
        suggestions = optimizer.ask_n_runs(3)
        assert len(suggestions) == 3

        optimizer.tell_run(
            suggestions[0].run_id,
            make_run(
                suggestions[0],
                state=RunState.FINISHED,
                summary={"loss": 6.0},
                history=[{"loss": 10.0}, {"loss": 6.0}, {"loss": 6.0}],
            ),
        )
        worst_running = make_run(
            suggestions[1],
            state=RunState.RUNNING,
            summary={"loss": 10.0},
            history=[{"loss": 10.0}, {"loss": 10.0}],
        )
        loss = self.better_running_loss
        better_running = make_run(
            suggestions[2],
            state=RunState.RUNNING,
            summary={"loss": loss},
            history=[{"loss": 10.0}, {"loss": loss}, {"loss": loss}],
        )
        optimizer.tell_run(suggestions[1].run_id, worst_running)
        optimizer.tell_run(suggestions[2].run_id, better_running)

        pruned = optimizer.prune_runs(
            [suggestions[1].run_id, suggestions[2].run_id],
            [worst_running, better_running],
        )
        assert pruned == [suggestions[1].run_id]

    def test_terminal_tell_after_prune_is_noop(self, optimizer: Optimizer) -> None:
        """A pruned run's terminal tell (and a repeated prune) must not raise.

        The scheduler stops a pruned run asynchronously, so the optimizer
        sees the run's terminal state on a later poll — after it may have
        already finalized the run at prune time.
        """
        suggestions = optimizer.ask_n_runs(3)
        runs = []
        for i, suggestion in enumerate(suggestions):
            run = make_run(
                suggestion,
                state=RunState.RUNNING,
                summary={"loss": float(10 * (i + 1))},
                history=[{"loss": float(10 * (i + 1))}] * 2,
            )
            optimizer.tell_run(suggestion.run_id, run)
            runs.append(run)
        run_ids = [s.run_id for s in suggestions]

        pruned = list(optimizer.prune_runs(run_ids, runs))
        for run_id, suggestion in zip(run_ids, suggestions, strict=True):
            if run_id not in pruned:
                continue
            optimizer.tell_run(
                run_id,
                make_run(suggestion, state=RunState.KILLED, summary={}),
            )
        # Offering an already-pruned id again must be tolerated.
        repruned = optimizer.prune_runs(run_ids, runs)
        assert set(repruned) <= set(run_ids)


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
                    reason=sspb.SweepSchedulerServerDoneTask.REASON_EXHAUSTED
                ),
                False,
            )
        )
        monkeypatch.setattr(client, "run_scheduler", mock)
        return mock

    @pytest.fixture
    def authenticated_api(self, monkeypatch):
        from unittest.mock import MagicMock

        from wandb.cli import cli

        api = MagicMock()
        api.is_authenticated = True
        api.settings.return_value = None
        monkeypatch.setattr(cli, "_get_cling_api", lambda *a, **k: api)
        return api

    def invoke(self, *args: str):
        from click.testing import CliRunner
        from wandb.cli import cli

        return CliRunner().invoke(cli.sweep_scheduler, args, catch_exceptions=False)

    def test_rejects_short_poll_interval(self, authenticated_api, run_scheduler_mock):
        result = self.invoke("--poll-interval", "1", "e/p/s")

        assert result.exit_code == 1
        run_scheduler_mock.assert_not_called()

    def test_rejects_nonpositive_batch_size(
        self, authenticated_api, run_scheduler_mock
    ):
        result = self.invoke("--batch-size", "0", "e/p/s")

        assert result.exit_code == 1
        run_scheduler_mock.assert_not_called()

    def test_malformed_sweep_id_exits_nonzero(
        self, authenticated_api, run_scheduler_mock
    ):
        """A bad sweep path must fail loudly, like the other validations."""
        result = self.invoke("a/b/c/d")

        assert result.exit_code != 0
        run_scheduler_mock.assert_not_called()

    def test_requires_entity_and_project(self, authenticated_api, run_scheduler_mock):
        result = self.invoke("bare-sweep-id")

        assert result.exit_code != 0
        assert "--entity and --project" in result.output
        run_scheduler_mock.assert_not_called()

    def test_forwards_options_to_host(self, authenticated_api, run_scheduler_mock):
        result = self.invoke("--batch-size", "4", "--poll-interval", "7", "e/p/s")

        assert result.exit_code == 0
        kwargs = run_scheduler_mock.call_args.kwargs
        assert kwargs["entity"] == "e"
        assert kwargs["project"] == "p"
        assert kwargs["sweep_id"] == "s"
        assert kwargs["batch_size"] == 4
        assert kwargs["poll_interval"] == 7.0

    def test_wandb_engine_builds_wandb_optimizer(
        self, authenticated_api, run_scheduler_mock
    ):
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

    def test_engine_is_required(self, authenticated_api, run_scheduler_mock):
        result = self.invoke("e/p/s")
        assert result.exit_code == 0

        make_optimizer = run_scheduler_mock.call_args.kwargs["make_optimizer"]
        no_engine = SweepInfo(id="s", name="s", entity="e", project="p", config={})
        with pytest.raises(Exception, match="engine"):
            make_optimizer(no_engine)

    def test_unsupported_engine_rejected(self, authenticated_api, run_scheduler_mock):
        result = self.invoke("e/p/s")
        assert result.exit_code == 0

        make_optimizer = run_scheduler_mock.call_args.kwargs["make_optimizer"]
        other_engine = SweepInfo(
            id="s",
            name="s",
            entity="e",
            project="p",
            config={"scheduler": {"engine": "genetic"}},
        )
        with pytest.raises(Exception, match="Unsupported engine"):
            make_optimizer(other_engine)

    def test_scheduler_failure_exits_nonzero(
        self, authenticated_api, run_scheduler_mock
    ):
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


class TestWandbEntryPoints:
    """The wandb engine's public entry points, matching optuna's and ax's."""

    @pytest.fixture
    def run_scheduler_mock(self, monkeypatch):
        from unittest.mock import MagicMock

        from wandb.sdk.sweeps.scheduler import wandb as wandb_scheduler

        mock = MagicMock()
        monkeypatch.setattr(wandb_scheduler, "run_scheduler", mock)
        return mock

    @pytest.fixture
    def create_sweep_mock(self, monkeypatch):
        from unittest.mock import MagicMock

        from wandb.sdk.sweeps.scheduler import wandb as wandb_scheduler

        mock = MagicMock(return_value="new_sweep")
        monkeypatch.setattr(wandb_scheduler, "wandb_sweep", mock)
        return mock

    def test_resume_sweep_drives_the_named_sweep(self, run_scheduler_mock) -> None:
        from wandb.sdk.sweeps.scheduler.client import SchedulerOptions
        from wandb.sdk.sweeps.scheduler.wandb import WandbOptimizer, resume_sweep

        resume_sweep(
            "e/p/s", options=SchedulerOptions(poll_interval_s=7.0, batch_size=4)
        )

        kwargs = run_scheduler_mock.call_args.kwargs
        assert (kwargs["entity"], kwargs["project"], kwargs["sweep_id"]) == (
            "e",
            "p",
            "s",
        )
        assert kwargs["poll_interval"] == 7.0
        assert kwargs["batch_size"] == 4
        optimizer = kwargs["make_optimizer"](make_scheduler_grid_sweep())
        assert isinstance(optimizer, WandbOptimizer)

    def test_resume_sweep_requires_a_full_path(self, run_scheduler_mock) -> None:
        from wandb.sdk.sweeps.scheduler.wandb import resume_sweep

        with pytest.raises(ValueError, match="entity/project/sweep_id"):
            resume_sweep("bare-id")

    def test_create_sweep_builds_a_config(
        self, run_scheduler_mock, create_sweep_mock
    ) -> None:
        from wandb.sdk.sweeps.scheduler.wandb import create_sweep

        create_sweep(
            "e",
            "p",
            {"lr": {"min": 0.0, "max": 1.0}},
            "loss",
            method="grid",
            goal="maximize",
            program_path="train.py",
        )

        sent = create_sweep_mock.call_args[0][0]
        assert sent == {
            "method": "grid",
            "metric": {"name": "loss", "goal": "maximize"},
            "parameters": {"lr": {"min": 0.0, "max": 1.0}},
            "scheduler": {"engine": "wandb"},
            "program": "train.py",
        }
        assert run_scheduler_mock.call_args.kwargs["sweep_id"] == "new_sweep"

    def test_create_sweep_rejects_an_empty_space(self, run_scheduler_mock) -> None:
        from wandb.sdk.sweeps.scheduler.wandb import create_sweep

        with pytest.raises(ValueError, match="parameters"):
            create_sweep("e", "p", {}, "loss")

    def test_create_sweep_from_config_records_the_engine(
        self, run_scheduler_mock, create_sweep_mock
    ) -> None:
        from wandb.sdk.sweeps.scheduler.wandb import create_sweep_from_config

        create_sweep_from_config(
            {"method": "grid", "parameters": {"x": {"values": [1]}}}, "e", "p"
        )

        sent = create_sweep_mock.call_args[0][0]
        assert sent["scheduler"] == {"engine": "wandb"}
        assert run_scheduler_mock.call_args.kwargs["sweep_id"] == "new_sweep"

    def test_create_sweep_from_config_rejects_another_engine(
        self, run_scheduler_mock
    ) -> None:
        from wandb.sdk.sweeps.scheduler.wandb import create_sweep_from_config

        with pytest.raises(ValueError, match="optuna"):
            create_sweep_from_config(
                {"scheduler": {"engine": "optuna"}, "parameters": {}}, "e", "p"
            )


class TestSchedulerHostOffMainThread:
    def test_sigint_handler_is_optional(self) -> None:
        """Entry points must work off the main thread, where signal cannot.

        Only the main thread may install a signal handler, and the public
        entry points are ordinary functions a caller may run in a worker.
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


class TerminatorContractTests(abc.ABC):
    """`should_terminate_sweep` must delegate to the caller's terminator."""

    @abc.abstractmethod
    def make_optimizer(self, terminator: Any = None) -> tuple[Optimizer, Any]:
        """Return an optimizer built with `terminator` and the callback's arg."""
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
