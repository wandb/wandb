from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeAlias

from typing_extensions import override

import wandb
from wandb import util
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.optimizer import (
    Optimizer,
    Run,
    RunConfig,
    RunSuggestion,
    RunWithMetrics,
    is_terminal_state,
)
from wandb.sdk.sweeps.sweep_info import SweepInfo

if TYPE_CHECKING:
    # Only used for static type checking, so referencing optuna's types below
    # doesn't force a real import at runtime for users who never touch this
    # scheduler.
    import optuna
    import optuna.distributions
    import optuna.pruners
    import optuna.trial
else:
    optuna = util.get_module(
        "optuna",
        required="wandb[optuna] is required to use the Optuna sweep scheduler. "
        "Please run `pip install wandb[optuna]`.",
    )

TrialConstructor: TypeAlias = Callable[["optuna.Trial"], dict[str, Any]]
TerminatorCallback: TypeAlias = Callable[["optuna.Study"], bool]

# optuna's `Study.stop` refuses to run outside an `optimize()` loop, so a
# sampler that stops the study from `after_trial` -- GridSampler does once the
# grid is spent -- surfaces as a RuntimeError carrying this text out of
# `study.tell`. Matching it is the documented ask-and-tell workaround; see
# https://github.com/optuna/optuna/issues/4121.
_STOP_OUTSIDE_OPTIMIZE_LOOP = "`Study.stop` is supposed to be invoked inside"

# Trial user attrs linking a study's trials to the sweep, so a study the
# caller persisted and reloaded is resumed on warm start instead of refilled.
_SWEEP_ATTR = "wandb_sweep"
_WANDB_RUN_ID_ATTR = "wandb_run_id"

# A claimed persisted trial that already finished, so its run has nothing
# left to tell.
_FINISHED = object()


@dataclass
class _PersistedIndex:
    """Run ids of the trials a reloaded study holds for the sweep."""

    # W&B run id to the run id of its still-running trial.
    running_by_run: dict[str, str] = field(default_factory=dict)
    # W&B run ids whose trial already finished.
    finished_runs: set[str] = field(default_factory=set)
    # Run ids of the sweep's running trials no run was seen for yet.
    unlinked_running: list[str] = field(default_factory=list)


@dataclass
class OptunaOptions:
    """The optuna settings `make_optimizer` builds an optimizer from.

    `study` is the optuna study to sample from. Pass exactly one of
    `distributions` (define-and-run) or `search_space` (define-by-run) to
    choose how it samples.

    A study reloaded from the caller's own storage may already hold this
    sweep's trials: each trial records its W&B run id as the
    `wandb_run_id` user attr. Warm start resumes those trials rather than
    adding the sweep's runs again, and adopts in-flight runs onto their
    still-running trials.

    `terminator` decides when the search itself is exhausted -- e.g.
    wrapping optuna's or OptunaHub's `Terminator.should_terminate`, or any
    custom stopping rule. It is the caller's own callback: nothing is
    loaded or configured on their behalf. The default `None` never
    terminates early.
    """

    study: optuna.Study | None = None
    distributions: dict[str, optuna.distributions.BaseDistribution] | None = None
    search_space: TrialConstructor | None = None
    terminator: TerminatorCallback | None = None


def _is_int(value: Any) -> bool:
    # bool is a subclass of int but is never a numeric bound here.
    return isinstance(value, int) and not isinstance(value, bool)


def _infer_distribution_name(parameter: dict[str, Any]) -> str:
    """Return the sweep distribution W&B infers when the spec names none."""
    if "min" not in parameter or "max" not in parameter:
        raise ValueError(
            f"Cannot infer an optuna distribution from sweep parameter: {parameter!r}"
        )
    lo, hi = parameter["min"], parameter["max"]
    return "int_uniform" if _is_int(lo) and _is_int(hi) else "uniform"


def _categorical_distribution(
    parameter: dict[str, Any],
) -> optuna.distributions.BaseDistribution:
    """Build a categorical distribution from `values` or a lone `value`."""
    if "values" in parameter:
        return optuna.distributions.CategoricalDistribution(list(parameter["values"]))
    return optuna.distributions.CategoricalDistribution([parameter["value"]])


def sweep_parameter_to_distribution(
    parameter: dict[str, Any],
) -> optuna.distributions.BaseDistribution:
    """Convert a W&B sweep parameter spec into an optuna distribution.

    The mapping, by the spec's `distribution` name, is:

    - `categorical` / `constant`; any spec with `value` (the constant
      shorthand); or a bare `values` spec with no `distribution` key
      -> `CategoricalDistribution`
    - `int_uniform` -> `IntDistribution(min, max)`
    - `uniform` -> `FloatDistribution(min, max)`
    - `log_uniform_values` -> `FloatDistribution(min, max, log=True)`
    - `q_uniform` -> `IntDistribution(min, max, step=q)` when `min`, `max`,
      and `q` are all integers, else `FloatDistribution(min, max, step=q)`
      (`q` defaults to 1)
    - `q_log_uniform_values` -> `IntDistribution(min, max, log=True, step=q)`
      (`q` defaults to 1), or `FloatDistribution(min, max, log=True)` with a
      `termwarn` (dropping `q`) when optuna can't represent it as a
      log-scale int distribution -- i.e. `q != 1` or `min < 1`
    - a numeric spec with no `distribution` key -> `int_uniform` or `uniform`,
      inferred from the `min`/`max` types as W&B does

    Sweep distributions with no optuna equivalent (e.g. `normal`, `beta`,
    `inv_log_uniform`, and exponent-space `log_uniform`) raise `ValueError`.
    """
    distributions = optuna.distributions

    # Constant / categorical shorthands: `distribution` is optional in W&B.
    if (
        "value" in parameter
        or "values" in parameter
        and "distribution" not in parameter
    ):
        return _categorical_distribution(parameter)

    # Without an explicit distribution, W&B infers one from min/max.
    dist = parameter.get("distribution") or _infer_distribution_name(parameter)

    if dist in ("categorical", "constant"):
        return _categorical_distribution(parameter)

    if dist == "int_uniform":
        return distributions.IntDistribution(parameter["min"], parameter["max"])

    if dist == "uniform":
        return distributions.FloatDistribution(parameter["min"], parameter["max"])

    if dist == "log_uniform_values":
        return distributions.FloatDistribution(
            parameter["min"], parameter["max"], log=True
        )

    if dist == "q_uniform":
        lo, hi, q = parameter["min"], parameter["max"], parameter.get("q", 1)
        # q_uniform is produced from both Int and Float stepped distributions;
        # pick the int variant only when every bound is integral.
        if _is_int(lo) and _is_int(hi) and _is_int(q):
            return distributions.IntDistribution(lo, hi, step=q)
        return distributions.FloatDistribution(lo, hi, step=q)

    if dist == "q_log_uniform_values":
        # optuna forbids step+log on floats, so this maps to a log-scale int
        # space -- but optuna also rejects IntDistribution(log=True) when
        # step != 1 or low < 1, so fall back to a (step-less) float space.
        lo, hi, q = parameter["min"], parameter["max"], parameter.get("q", 1)
        if q != 1 or lo < 1:
            wandb.termwarn(
                "Sweep parameter has a q_log_uniform_values distribution "
                f"with min={lo!r}, q={q!r} that optuna cannot represent as "
                "a log-scale int distribution (it requires step=1 and "
                "min>=1). Converting to a FloatDistribution(log=True) "
                "instead; q will be ignored."
            )
            return distributions.FloatDistribution(lo, hi, log=True)
        return distributions.IntDistribution(lo, hi, log=True, step=int(q))

    raise ValueError(
        f"Sweep distribution {dist!r} has no optuna equivalent and cannot be converted."
    )


def search_space_from_sweep_config(
    parameters: dict[str, Any],
) -> dict[str, optuna.distributions.BaseDistribution]:
    """Convert a sweep config's `parameters` block into an optuna search space.

    Maps each `name -> spec` entry onto a `name -> distribution` entry.
    """
    return {
        name: sweep_parameter_to_distribution(spec) for name, spec in parameters.items()
    }


class OptunaOptimizer(Optimizer):
    """Base `Optimizer` driving a W&B sweep from an optuna study.

    Subclasses supply the search space, either up front as distributions or by
    running a define-by-run constructor.
    """

    @override
    def __init__(
        self,
        study: optuna.Study,
        sweep: SweepInfo,
        terminator: TerminatorCallback | None = None,
    ):
        self.study = study
        # Live ask()'d trials kept by str(trial.number). The study only
        # stores frozen trials, which lack report()/should_prune(), so we
        # must hold the live ones to record intermediate values (and, next,
        # drive pruning).
        self.trials: dict[str, optuna.Trial] = {}
        self._terminator = terminator
        # Each trial's highest reported step. Every tell carries the run's
        # full (re)sampled history, but optuna ignores a re-reported step
        # and warns about it, so only steps past this mark are reported.
        self._last_reported_step: dict[str, int] = {}
        # Set when a sampler asks the study to stop; see `_tell_study`.
        self._stop_requested = False
        # Live trials already stamped with their W&B run id.
        self._linked: set[str] = set()

        super().__init__(sweep)

        self._sweep_path = f"{sweep.entity}/{sweep.project}/{sweep.id}"
        # Built on the first warm-start call and dropped once generation
        # starts; see `_index_persisted_trials`.
        self._warm_start_over = False
        self._persisted_index: _PersistedIndex | None = None

    def _index_persisted_trials(self) -> _PersistedIndex:
        """Index the trials a caller's study already holds for this sweep.

        Only run ids are kept, never the trials: linked trials by W&B run
        id, and running trials this sweep asked for but never saw polled,
        which carry no run id yet and are matched to their run by params.
        """
        index = _PersistedIndex()
        # Every storage's cache holds these once the study is first asked
        # for a trial; deepcopy=False lists them without copying.
        for trial in self.study.get_trials(deepcopy=False):
            wandb_run_id = trial.user_attrs.get(_WANDB_RUN_ID_ATTR)
            running = trial.state == optuna.trial.TrialState.RUNNING
            if wandb_run_id is not None:
                if running:
                    index.running_by_run[wandb_run_id] = str(trial.number)
                else:
                    index.finished_runs.add(wandb_run_id)
            elif running and trial.user_attrs.get(_SWEEP_ATTR) == self._sweep_path:
                index.unlinked_running.append(str(trial.number))
        return index

    def _claim_persisted_trial(self, data: Run) -> Any:
        """Take the study's existing trial for a warm-start run.

        Returns:
            The run id of the run's still-running trial, `_FINISHED` if its
            trial already finished, or None if the study has none.
        """
        if self._warm_start_over:
            return None
        if self._persisted_index is None:
            self._persisted_index = self._index_persisted_trials()
        index = self._persisted_index
        if data.wandb_run_id in index.finished_runs:
            index.finished_runs.discard(data.wandb_run_id)
            return _FINISHED
        run_id = index.running_by_run.pop(data.wandb_run_id, None)
        if run_id is not None or not index.unlinked_running:
            return run_id
        config = data.config.flat_dict()
        for i, candidate in enumerate(index.unlinked_running):
            params = self._stored_trial(self._trial_id(candidate)).params
            if params and all(
                name in config and config[name] == value
                for name, value in params.items()
            ):
                return index.unlinked_running.pop(i)
        return None

    def _end_warm_start(self) -> None:
        """Drop the warm-start index; later runs are the scheduler's own."""
        self._warm_start_over = True
        self._persisted_index = None

    def _trial_id(self, run_id: str) -> int:
        """Return the storage id of the study's trial with this run id."""
        # optuna has no public lookup by trial number short of listing
        # every trial; the storage resolves one number directly.
        return self.study._storage.get_trial_id_from_study_id_trial_number(
            self.study._study_id, int(run_id)
        )

    def _stored_trial(self, trial_id: int) -> optuna.trial.FrozenTrial:
        """Return one trial as the storage holds it, uncopied."""
        return self.study._storage.get_trial(trial_id)

    def _resume_trial(self, run_id: str, wandb_run_id: str) -> str:
        """Track a persisted running trial as live again; return its run id."""
        trial_id = self._trial_id(run_id)
        steps = self._stored_trial(trial_id).intermediate_values
        self.trials[run_id] = optuna.trial.Trial(self.study, trial_id)
        if steps:
            self._last_reported_step[run_id] = max(steps)
        self._link(run_id, wandb_run_id)
        return run_id

    def _link(self, run_id: str, wandb_run_id: str) -> None:
        """Record a live trial's W&B run id in the study, once."""
        if run_id in self._linked or not wandb_run_id:
            return
        self.trials[run_id].set_user_attr(_WANDB_RUN_ID_ATTR, wandb_run_id)
        self._linked.add(run_id)

    def _release(self, run_id: str) -> optuna.Trial | None:
        """Stop tracking a live trial, returning it if it was tracked."""
        self._last_reported_step.pop(run_id, None)
        self._linked.discard(run_id)
        return self.trials.pop(run_id, None)

    @property
    def _is_multi_objective(self) -> bool:
        """Whether the study optimizes more than one objective."""
        return len(self.study.directions) > 1

    def _tell_study(
        self,
        trial: optuna.Trial,
        values: Any = None,
        *,
        state: optuna.trial.TrialState,
    ) -> None:
        """Finalize a trial, absorbing a sampler's request to stop the study.

        optuna records the trial's outcome before running the sampler's
        `after_trial` hook, so the outcome is already durable when a stop
        request surfaces from it. Letting that escape would fail the tell for
        a run the study accepted, and the scheduler would retire the run as a
        tell error. The request is remembered instead, so the next ask
        reports the search as exhausted.

        Args:
            trial: The live trial to finalize.
            values: The trial's objective value(s), or None if it has none.
            state: The terminal state to record the trial in.

        Raises:
            RuntimeError: Any error from `after_trial` other than a sampler
                asking the study to stop.
        """
        try:
            self.study.tell(trial, values, state=state)
        except RuntimeError as e:
            if _STOP_OUTSIDE_OPTIMIZE_LOOP not in str(e):
                raise
            self._stop_requested = True

    def _search_is_exhausted(self) -> bool:
        """Whether the study has no unexplored point left to propose.

        A sampler over a finite space does not refuse a further ask: optuna's
        GridSampler hands out a *duplicate* grid point (warning as it goes)
        once the grid is spent, so asking again would re-run finished work
        forever. Samplers over an unbounded space never report exhaustion.
        """
        if self._stop_requested:
            return True
        # `is_exhausted` is GridSampler's; other samplers don't define it.
        is_exhausted = getattr(self.study.sampler, "is_exhausted", None)
        return is_exhausted is not None and bool(is_exhausted(self.study))

    @abstractmethod
    def _ask_suggestion(self) -> RunSuggestion:
        """Ask the study for one trial and describe it as a run to start."""
        ...

    def _track(self, trial: optuna.Trial, params: dict[str, Any]) -> RunSuggestion:
        """Keep a live trial and describe it to the scheduler.

        The run id is `str(trial.number)`, which is how `tell_run` and
        `prune_run` find the trial again.
        """
        run_id = str(trial.number)
        self.trials[run_id] = trial
        trial.set_user_attr(_SWEEP_ATTR, self._sweep_path)
        return RunSuggestion(config=RunConfig.from_values(params), run_id=run_id)

    @override
    def ask_n_runs(self, n: int) -> Sequence[RunSuggestion]:
        """Propose up to `n` runs to start next.

        Returns fewer than `n` -- possibly none, which finishes the sweep --
        once the study has no unexplored point left to offer.

        Args:
            n: The maximum number of runs to propose.
        """
        # Warm start is over once the scheduler asks for new runs.
        self._end_warm_start()
        suggestions = []
        for _ in range(n):
            if self._search_is_exhausted():
                break
            suggestions.append(self._ask_suggestion())
        return suggestions

    @override
    def should_terminate_sweep(self) -> bool:
        """Return True once the caller's `terminator` says the search is done.

        `terminator` is supplied via `OptunaOptions`; the default is `None`,
        which never terminates early.
        """
        return self._terminator is not None and self._terminator(self.study)

    @override
    def validate_sweep_objective(self) -> None:
        """Fail fast if the study and the sweep disagree on the objective.

        The study's optimization direction(s) must match the sweep metric
        goal(s), and — when the study declares metric names — its objective
        names must match the sweep metric names. Otherwise the optimizer would
        silently search the wrong way or against the wrong metric. The study
        and sweep are supplied independently (e.g. via `resume_sweep` or a
        user-provided study factory), so the two can drift; the sweep config is
        the source of truth.
        """
        metrics = self._sweep.config.get("metrics")
        if metrics is not None:
            if len(self.study.directions) != len(metrics):
                raise ValueError(
                    f"Study has {len(self.study.directions)} objectives but the "
                    f"sweep config declares {len(metrics)} metrics."
                )
            sweep_directions = [
                str(metric.get("goal", "minimize")).lower() for metric in metrics
            ]
            study_directions = [d.name.lower() for d in self.study.directions]
            if study_directions != sweep_directions:
                raise ValueError(
                    f"Study directions {study_directions!r} do not match the "
                    f"sweep metric goals {sweep_directions!r}; create the study "
                    f"with directions={sweep_directions!r}."
                )
            metric_names = getattr(self.study, "metric_names", None)
            if metric_names:
                sweep_names = [metric["name"] for metric in metrics if "name" in metric]
                if sweep_names and list(metric_names) != sweep_names:
                    raise ValueError(
                        f"Study metric names {list(metric_names)!r} do not match "
                        f"the sweep metric names {sweep_names!r}."
                    )
            return

        if len(self.study.directions) != 1:
            raise ValueError(
                "OptunaOptimizer only supports single-objective studies; the "
                f"study has {len(self.study.directions)} objectives."
            )

        metric = self._sweep.config.get("metric") or {}
        goal = str(metric.get("goal", "minimize")).lower()
        study_direction = self.study.direction.name.lower()
        if study_direction != goal:
            raise ValueError(
                f"Study direction {study_direction!r} does not match the sweep "
                f"metric goal {goal!r}; create the study with direction={goal!r}."
            )

        # optuna's objective names are optional metadata; validate only when
        # set.
        metric_names = getattr(self.study, "metric_names", None)
        if metric_names:
            metric_name = self.metric_key()
            if metric_names[0] != metric_name:
                raise ValueError(
                    f"Study metric name {metric_names[0]!r} does not match the "
                    f"sweep metric name {metric_name!r}."
                )

    def trial_state(self, state: RunState) -> optuna.trial.TrialState:
        """Map a sweep `RunState` onto the optuna `TrialState` it stands for.

        Raises:
            ValueError: If a new `RunState` member has no mapping here.
        """
        if state.is_alive:
            # RUNNING/PENDING/PREEMPTING/UNKNOWN: still producing results.
            return optuna.trial.TrialState.RUNNING
        if state == RunState.FINISHED:
            return optuna.trial.TrialState.COMPLETE
        if state in (
            RunState.FAILED,
            RunState.CRASHED,
            RunState.KILLED,
            RunState.PREEMPTED,
        ):
            return optuna.trial.TrialState.FAIL
        raise ValueError(f"Unhandled run state: {state}")

    @override
    def tell_run(self, run_id: Any, data: RunWithMetrics) -> None:
        """Report a run's intermediate values and finalize it once terminal.

        A run whose trial was already finalized -- at prune time, or by an
        earlier terminal tell -- is a no-op, per the Optimizer contract.
        """
        # run_id is str(trial.number), set in ask_n_runs.
        trial = self.trials.get(run_id)
        if trial is None:
            return
        self._link(run_id, data.wandb_run_id)
        # optuna's intermediate values feed its pruners, which are
        # single-objective only, so a multi-objective study rejects them.
        if not self._is_multi_objective:
            last = self._last_reported_step.get(run_id, -1)
            for row in data.history_metrics:
                if "_step" not in row:
                    raise ValueError(
                        "Sampled history is missing '_step'; cannot report "
                        "intermediate values for pruning/early-termination."
                    )
                step = row["_step"]
                if step <= last:
                    continue
                value = self.metric_value(row)
                if value is not None:
                    trial.report(value, step=step)
                    last = step
            self._last_reported_step[run_id] = last

        state = self.trial_state(data.state)
        if state == optuna.trial.TrialState.COMPLETE:
            values = self.objective_values(data.summary_metrics)
            if values is None:
                # A run that finished without every objective taught the
                # search nothing; record a failure rather than telling the
                # study a missing value.
                self._tell_study(trial, state=optuna.trial.TrialState.FAIL)
            elif self._is_multi_objective:
                self._tell_study(trial, values, state=state)
            else:
                self._tell_study(trial, values[0], state=state)
        elif state == optuna.trial.TrialState.FAIL:
            self._tell_study(trial, state=state)
        else:
            # RUNNING: only intermediate values are reported; the trial is
            # finalized later (on completion/failure) or by prune_run.
            return
        # The study now owns the trial's outcome; drop the live handle so a
        # repeated terminal tell cannot finalize it twice.
        self._release(run_id)

    @override
    def forget_run(self, run_id: Any) -> None:
        """Fail the trial of a proposed run that will never start.

        Failing (rather than leaving it running) frees the trial's slot in
        samplers that limit concurrency.
        """
        trial = self._release(run_id)
        if trial is None:
            return
        self._tell_study(trial, state=optuna.trial.TrialState.FAIL)

    @override
    def prune_run(self, run_id: Any, data: RunWithMetrics) -> bool:
        """Return True if the study's pruner says the run should stop early.

        A run whose trial was already finalized is never pruned again.
        """
        # tell_run already reported this poll's intermediate values, so the
        # study's pruner can decide. On a prune, finalize the trial as PRUNED.
        trial = self.trials.get(run_id)
        if trial is None:
            return False
        if self._is_multi_objective:
            # optuna's pruners rank against a single best value, so they
            # cannot judge a multi-objective trial.
            return False
        if not trial.should_prune():
            return False
        self._tell_study(trial, state=optuna.trial.TrialState.PRUNED)
        self._release(run_id)
        return True

    @override
    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an in-flight run, resuming its trial if the study has one.

        A study the caller persisted may already hold the run's trial. A
        running one is tracked as live again, keeping its reported values;
        a finished one already records the run's outcome, so the run is left
        untracked rather than duplicated.

        Otherwise, enqueuing the run's params makes the next ask() (via
        _ask_suggestion, which also handles the imperative conditional
        branch) return a trial fixed to them. The trial is left RUNNING —
        not told — so the loop reports its intermediate values for pruning
        and finalizes it via tell_run when the run completes.

        Returns:
            The trial number to track the run by, or None if the study
            already finished the run's trial.
        """
        claimed = self._claim_persisted_trial(data)
        if claimed is _FINISHED:
            return None
        if claimed is not None:
            return self._resume_trial(claimed, data.wandb_run_id)
        self.study.enqueue_trial(data.config.flat_dict())
        # Asks directly rather than through ask_n_runs: the enqueued params
        # are fixed, so they cost the search nothing and an exhausted space
        # must still adopt the run rather than leave it untracked.
        run_id = self._ask_suggestion().run_id
        self._link(run_id, data.wandb_run_id)
        return run_id

    @override
    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        """Warm-start the study with a run that already stopped.

        A study the caller persisted may already hold the run's trial. A
        finished one is left as is; a running one -- the run ended while no
        scheduler watched it -- is finalized with the run's result. Only a
        run the study has never seen becomes a new trial.
        """
        if not is_terminal_state(data.state):
            return
        claimed = self._claim_persisted_trial(data)
        if claimed is None:
            self._add_finished_trial(data)
        elif claimed is not _FINISHED:
            self.tell_run(self._resume_trial(claimed, data.wandb_run_id), data)

    @abstractmethod
    def _add_finished_trial(self, data: RunWithMetrics) -> None:
        """Record a terminal run the study has no trial for as a new trial."""
        ...


class OptunaDeclarativeOptimizer(OptunaOptimizer):
    """Define-and-run: the space is supplied up front as distributions.

    The distributions are known before any trial runs, so the sweep is built
    directly from them and each ask passes them to `study.ask`.
    """

    @override
    def __init__(
        self,
        study: optuna.Study,
        distributions: dict[str, optuna.distributions.BaseDistribution],
        sweep: SweepInfo,
        terminator: TerminatorCallback | None = None,
    ):
        self.distributions = distributions
        super().__init__(study, sweep, terminator)

    @override
    def _ask_suggestion(self) -> RunSuggestion:
        """Sample one trial from the declared distributions."""
        trial = self.study.ask(self.distributions)
        return self._track(trial, trial.params)

    @override
    def _add_finished_trial(self, data: RunWithMetrics) -> None:
        """Record a run as a historical trial.

        The flat search space is known up front, so add_trial() is the lightest
        faithful path — no extra ask(). Runs whose config doesn't cover the
        search space are skipped (create_trial requires an exact param match).
        """
        trial_state = self.trial_state(data.state)  # COMPLETE or FAIL
        values = None
        if trial_state == optuna.trial.TrialState.COMPLETE:
            values = self.objective_values(data.summary_metrics)
            if values is None:
                return  # finished but never logged every objective metric
        config = data.config.flat_dict()
        if not all(name in config for name in self.distributions):
            return
        params = {name: config[name] for name in self.distributions}
        self.study.add_trial(
            optuna.trial.create_trial(
                params=params,
                distributions=self.distributions,
                values=values,
                state=trial_state,
                user_attrs={
                    _SWEEP_ATTR: self._sweep_path,
                    _WANDB_RUN_ID_ATTR: data.wandb_run_id,
                },
            )
        )


class OptunaImperativeOptimizer(OptunaOptimizer):
    """Define-by-run: the space is discovered by a TrialConstructor.

    The constructor's `trial.suggest_*` calls implicitly define the space. We
    run it once against a throwaway trial to record the distributions, build the
    sweep from them, then re-run it on each ask for real suggestions.
    """

    @override
    def __init__(
        self,
        study: optuna.Study,
        trial_constructor: TrialConstructor,
        sweep: SweepInfo,
        terminator: TerminatorCallback | None = None,
    ):
        self.trial_constructor = trial_constructor
        super().__init__(study, sweep, terminator)

    @override
    def _ask_suggestion(self) -> RunSuggestion:
        """Sample one trial, running the constructor to define its params."""
        trial = self.study.ask()
        # A define-by-run constructor returns the flat {param: value} mapping.
        return self._track(trial, self.trial_constructor(trial))

    @override
    def _add_finished_trial(self, data: RunWithMetrics) -> None:
        """Replay a run through the constructor.

        Enqueuing the run's params makes the next ask() take the same (possibly
        conditional) branch, so the recreated trial's distributions match the
        run; tell_run then finalizes it on the study.
        """
        # A finished run with no objective value would make tell_run pass None
        # to a COMPLETE study.tell(), so skip it.
        if (
            data.state == RunState.FINISHED
            and self.objective_values(data.summary_metrics) is None
        ):
            return
        # Never skip_if_exists: two prior runs can share a config, and a
        # skipped enqueue would leave ask() free to sample a fresh point that
        # then gets told this run's result -- teaching the study a value the
        # params never produced. Repeated params are a faithful warm start.
        self.study.enqueue_trial(data.config.flat_dict())
        # Asks directly rather than through ask_n_runs, as the enqueued params
        # are fixed and so cost an exhausted space nothing.
        self.tell_run(self._ask_suggestion().run_id, data)


# ---------------------------------------------------------------------------
# Optimizer construction.
#
# `wandb sweep-scheduler` builds an optimizer through these rather than
# instantiating the classes above: the flavor (define-and-run vs
# define-by-run) is chosen by which of `distributions` or `search_space`
# the sweep's config supplies.
# ---------------------------------------------------------------------------


def create_study_from_sweep_config(config: dict[str, Any]) -> optuna.Study:
    """Build an optuna study from a sweep config's metric objective(s).

    When `config["metrics"]` is set, a multi-objective study is created with
    `directions=` derived from each entry's `goal` (default `"minimize"`).
    Otherwise a single-objective study is created from
    `config["metric"]["goal"]`.
    """
    metrics = config.get("metrics")
    pruner = optuna.pruners.NopPruner()
    if metrics is not None:
        directions = [str(metric.get("goal", "minimize")).lower() for metric in metrics]
        return optuna.create_study(directions=directions, pruner=pruner)
    goal = (config.get("metric") or {}).get("goal", "minimize")
    return optuna.create_study(direction=goal, pruner=pruner)


def make_optimizer(
    study: optuna.Study, sweep: SweepInfo, options: OptunaOptions
) -> OptunaOptimizer:
    """Build the optimizer flavor the options select.

    Exactly one of `options.distributions` (define-and-run) or
    `options.search_space` (define-by-run) chooses how the study samples.

    Raises:
        ValueError: If neither or both parameter-space options are given.
    """
    if (options.distributions is None) == (options.search_space is None):
        raise ValueError("provide exactly one of `distributions` or `search_space`")
    if options.distributions is not None:
        return OptunaDeclarativeOptimizer(
            study, options.distributions, sweep, options.terminator
        )
    assert options.search_space is not None  # guaranteed by the check above
    return OptunaImperativeOptimizer(
        study, options.search_space, sweep, options.terminator
    )
