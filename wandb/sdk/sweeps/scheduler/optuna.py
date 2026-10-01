from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias

from typing_extensions import override

import wandb
from wandb import util
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.client import load_optimizer_config, load_source_object
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

_TRIAL_OUTCOME_VERB: dict[optuna.trial.TrialState, str] = {
    optuna.trial.TrialState.COMPLETE: "finished",
    optuna.trial.TrialState.PRUNED: "pruned",
    optuna.trial.TrialState.FAIL: "failed",
}

# Optuna's ask/tell API logs nothing on tell, so the optimizer logs outcomes.
_logger = logging.getLogger("optuna.wandb_scheduler")

TrialConstructor: TypeAlias = Callable[["optuna.Trial"], dict[str, Any]]
TerminatorCallback: TypeAlias = Callable[["optuna.Study"], bool]

# optuna's `Study.stop` refuses to run outside an `optimize()` loop, so a
# sampler that stops the study from `after_trial` -- GridSampler does once the
# grid is spent -- surfaces as a RuntimeError carrying this text out of
# `study.tell`. Matching it is the documented ask-and-tell workaround; see
# https://github.com/optuna/optuna/issues/4121.
_STOP_OUTSIDE_OPTIMIZE_LOOP = "`Study.stop` is supposed to be invoked inside"


@dataclass
class OptunaOptions:
    """The optuna settings `make_optimizer` builds an optimizer from.

    `study` is the optuna study to sample from. Pass exactly one of
    `distributions` (define-and-run) or `search_space` (define-by-run) to
    choose how it samples.

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


_STEP_TOLERANCE = 1e-8


def _run_param_value(
    name: str,
    config: dict[str, Any],
    distribution: optuna.distributions.BaseDistribution,
) -> Any:
    """Return a prior run's value for one search space parameter.

    The value is converted to the distribution's type: a run's config
    round-trips through JSON, which turns a float like `1.0` into `1`.

    Raises:
        ValueError: If the config has no value for the parameter, or the
            value is not one the distribution can produce.
    """
    if name not in config:
        raise ValueError(
            f"The run's config has no value for search space parameter {name!r}."
        )
    value = config[name]

    if isinstance(distribution, optuna.distributions.CategoricalDistribution):
        try:
            index = distribution.to_internal_repr(value)
        except ValueError:
            raise ValueError(
                f"The run's config sets {name!r} to {value!r}, but the search "
                f"space expects one of {list(distribution.choices)!r}."
            ) from None
        return distribution.to_external_repr(index)

    if not isinstance(
        distribution,
        (optuna.distributions.FloatDistribution, optuna.distributions.IntDistribution),
    ):
        return value

    if not _is_in_range_distribution(value, distribution):
        raise ValueError(
            f"The run's config sets {name!r} to {value!r}, but the search space "
            f"expects {_describe_range_distribution(distribution)}."
        )
    return distribution.to_external_repr(distribution.to_internal_repr(value))


def _is_in_range_distribution(
    value: Any,
    distribution: optuna.distributions.FloatDistribution
    | optuna.distributions.IntDistribution,
) -> bool:
    """Whether a numeric distribution can produce the value."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    # NaN fails the range comparison, so it is rejected here too.
    if not distribution.low <= value <= distribution.high:
        return False

    step = distribution.step
    if isinstance(distribution, optuna.distributions.IntDistribution):
        return float(value).is_integer() and (value - distribution.low) % step == 0
    if step is None:
        return True
    k = (value - distribution.low) / step
    # Matches the tolerance of Optuna's own FloatDistribution check.
    return abs(k - round(k)) < _STEP_TOLERANCE


def _describe_range_distribution(
    distribution: optuna.distributions.FloatDistribution
    | optuna.distributions.IntDistribution,
) -> str:
    """Describe the values a numeric distribution produces, for an error."""
    is_int = isinstance(distribution, optuna.distributions.IntDistribution)
    kind = "an integer" if is_int else "a number"
    description = f"{kind} from {distribution.low} to {distribution.high}"
    if distribution.step is None or (is_int and distribution.step == 1):
        return description
    return f"{description} in steps of {distribution.step}"


class _WarmStartTrial(optuna.trial.FixedTrial):
    """Replays a prior run's config through a define-by-run constructor.

    Each suggestion is checked before the constructor sees it, so a config
    that lacks a parameter or holds an invalid value fails with a message
    naming the parameter, and `run_params` holds only valid values.
    """

    @override
    def __init__(self, config: dict[str, Any], study: optuna.Study) -> None:
        super().__init__(config)
        self._config = config
        self._study = study
        self.run_params: dict[str, Any] = {}

    @property
    def study(self) -> optuna.Study:
        """The study being warm-started, as on a real `optuna.Trial`."""
        return self._study

    def _check(
        self,
        name: str,
        distribution: optuna.distributions.BaseDistribution,
    ) -> None:
        """Record the run's value for a parameter, or raise if it is invalid."""
        self.run_params[name] = _run_param_value(name, self._config, distribution)

    @override
    def suggest_float(
        self,
        name: str,
        low: float,
        high: float,
        *,
        step: float | None = None,
        log: bool = False,
    ) -> float:
        self._check(
            name,
            optuna.distributions.FloatDistribution(low, high, log=log, step=step),
        )
        return super().suggest_float(name, low, high, step=step, log=log)

    @override
    def suggest_int(
        self,
        name: str,
        low: int,
        high: int,
        *,
        step: int = 1,
        log: bool = False,
    ) -> int:
        self._check(
            name,
            optuna.distributions.IntDistribution(low, high, log=log, step=step),
        )
        return super().suggest_int(name, low, high, step=step, log=log)

    @override
    def suggest_categorical(
        self,
        name: str,
        choices: Sequence[optuna.distributions.CategoricalChoiceType],
    ) -> optuna.distributions.CategoricalChoiceType:
        self._check(name, optuna.distributions.CategoricalDistribution(choices))
        return super().suggest_categorical(name, choices)


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

        super().__init__(sweep)

    @override
    def route_library_logs(self, handler: logging.Handler) -> Callable[[], None]:
        """Swap optuna's default stderr handler for `handler`.

        Uses optuna's public logging switches: the "optuna" logger stops
        propagation, so it alone sees every record the library emits.
        """
        library_logger = logging.getLogger("optuna")
        verbosity = optuna.logging.get_verbosity()
        optuna.logging.disable_default_handler()
        library_logger.addHandler(handler)
        if verbosity > logging.INFO:
            optuna.logging.set_verbosity(logging.INFO)

        def restore() -> None:
            library_logger.removeHandler(handler)
            optuna.logging.set_verbosity(verbosity)
            optuna.logging.enable_default_handler()

        return restore

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
        _logger.info(
            "Trial %d %s%s and parameters: %s.",
            trial.number,
            _TRIAL_OUTCOME_VERB.get(state, state.name.lower()),
            f" with value: {values}" if values is not None else "",
            trial.params,
        )

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

    @abstractmethod
    def _warm_start_params(self, config: dict[str, Any]) -> dict[str, Any]:
        """Return a prior run's value for each search space parameter.

        Args:
            config: The run's flat config.

        Raises:
            ValueError: If the config does not set every parameter to a value
                the search space can produce.
        """
        ...

    def _track(self, trial: optuna.Trial, params: dict[str, Any]) -> RunSuggestion:
        """Keep a live trial and describe it to the scheduler.

        The run id is `str(trial.number)`, which is how `tell_run` and
        `prune_run` find the trial again.
        """
        run_id = str(trial.number)
        self.trials[run_id] = trial
        return RunSuggestion(config=RunConfig.from_values(params), run_id=run_id)

    @override
    def ask_n_runs(self, n: int) -> Sequence[RunSuggestion]:
        """Propose up to `n` runs to start next.

        Returns fewer than `n` -- possibly none, which finishes the sweep --
        once the study has no unexplored point left to offer.

        Args:
            n: The maximum number of runs to propose.
        """
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
        del self.trials[run_id]
        self._last_reported_step.pop(run_id, None)

    @override
    def forget_run(self, run_id: Any) -> None:
        """Fail the trial of a proposed run that will never start.

        Failing (rather than leaving it running) frees the trial's slot in
        samplers that limit concurrency.
        """
        trial = self.trials.pop(run_id, None)
        self._last_reported_step.pop(run_id, None)
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
        del self.trials[run_id]
        self._last_reported_step.pop(run_id, None)
        return True

    @override
    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an in-flight run by recreating a live trial for its params.

        Enqueuing the run's params makes the next ask() (via _ask_suggestion,
        which also handles the imperative conditional branch) return a trial
        fixed to them. The trial is left RUNNING — not told — so the loop
        reports its intermediate values for pruning and finalizes it via
        tell_run when the run completes.

        Returns:
            The trial number to track the run by.

        Raises:
            ValueError: If the run's config does not set every search space
                parameter to a value the space can produce.
        """
        self.study.enqueue_trial(self._warm_start_params(data.config.flat_dict()))
        # Asks directly rather than through ask_n_runs: the enqueued params
        # are fixed, so they cost the search nothing and an exhausted space
        # must still adopt the run rather than leave it untracked.
        return self._ask_suggestion().run_id


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
    def _warm_start_params(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            name: _run_param_value(name, config, distribution)
            for name, distribution in self.distributions.items()
        }

    @override
    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        """Warm-start the study by recording a run as a historical trial.

        The flat search space is known up front, so add_trial() is the lightest
        faithful path — no extra ask().

        Raises:
            ValueError: If the run's config does not set every search space
                parameter to a value the space can produce.
        """
        if not is_terminal_state(data.state):
            return
        trial_state = self.trial_state(data.state)  # COMPLETE or FAIL
        values = None
        if trial_state == optuna.trial.TrialState.COMPLETE:
            values = self.objective_values(data.summary_metrics)
            if values is None:
                return  # finished but never logged every objective metric
        params = self._warm_start_params(data.config.flat_dict())
        self.study.add_trial(
            optuna.trial.create_trial(
                params=params,
                distributions=self.distributions,
                values=values,
                state=trial_state,
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
    def _warm_start_params(self, config: dict[str, Any]) -> dict[str, Any]:
        # A replay finds the run's branch without adding a trial to the study.
        replay = _WarmStartTrial(config, self.study)
        try:
            params = self.trial_constructor(replay)
        except AttributeError as e:
            if e.obj is not replay:
                raise
            function_name = getattr(self.trial_constructor, "__name__", "")
            raise ValueError(
                f"The `scheduler.search_space` function {function_name!r} uses"
                f" `trial.{e.name}`, which is unavailable when warm-starting"
                f" from a prior run. Remove `trial.{e.name}` from the function"
                " to warm-start from prior runs."
            ) from None
        if not isinstance(params, dict):
            kind = "None" if params is None else f"a {type(params).__name__}"
            raise TypeError(
                f"The scheduler.search_space function returned {kind}; it must"
                " return a dict mapping parameter names to values"
            )
        return replay.run_params

    @override
    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        """Warm-start the study by replaying a run through the constructor.

        Enqueuing the run's params makes the next ask() take the same (possibly
        conditional) branch, so the recreated trial's distributions match the
        run; tell_run then finalizes it on the study.

        Raises:
            ValueError: If the run's config does not set every search space
                parameter to a value the space can produce.
        """
        if not is_terminal_state(data.state):
            return
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
        self.study.enqueue_trial(self._warm_start_params(data.config.flat_dict()))
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


def build_optuna_optimizer(
    sweep: SweepInfo, scheduler_config: dict[str, Any]
) -> OptunaOptimizer:
    """Build the optimizer for a sweep whose `scheduler.engine` is `optuna`.

    `scheduler.optimizer` names a zero-argument function in
    `scheduler.source`. The function may return either an Optuna `Study` or
    a `(Study, terminator)` tuple. A terminator is a one-argument function
    that receives the study after each generation and finishes the sweep by
    returning `True`, such as `optuna.terminator.Terminator().should_terminate`.
    """
    optimizer_name: str = scheduler_config.get("optimizer", "")
    search_space_name: str | None = scheduler_config.get("search_space")
    source: str = scheduler_config.get("source", "")

    # `search_space` picks how the parameter space is defined: when given,
    # the loaded function is the define-by-run trial constructor; otherwise
    # a declarative parameter space is derived from the sweep's
    # `parameters`. Independently, `optimizer` names a study factory to
    # call instead of building the study from the config.
    search_space = None
    distributions = None
    try:
        if search_space_name is not None:
            search_space = load_source_object(source, search_space_name)
        else:
            distributions = search_space_from_sweep_config(
                sweep.config.get("parameters", {})
            )
        terminator = None
        if optimizer_name:
            study, terminator = load_optimizer_config(
                source, optimizer_name, "optuna.study.Study"
            )
        else:
            study = create_study_from_sweep_config(sweep.config)
    except ValueError as e:
        raise wandb.Error(str(e)) from e

    return make_optimizer(
        study,
        sweep,
        OptunaOptions(
            study=study,
            distributions=distributions,
            search_space=search_space,
            terminator=terminator,
        ),
    )
