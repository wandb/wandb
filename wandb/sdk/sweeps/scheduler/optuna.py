from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias

from typing_extensions import override

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
    import optuna.trial
else:
    optuna = util.get_module(
        "optuna",
        required="wandb[optuna] is required to use the Optuna sweep scheduler. "
        "Please run `pip install wandb[optuna]`.",
    )

TrialConstructor: TypeAlias = Callable[["optuna.Trial"], dict[str, Any]]
TerminatorCallback: TypeAlias = Callable[["optuna.Study"], bool]


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
    - `q_log_uniform_values` -> `IntDistribution(min, max, log=True, step=q)`
      (`q` defaults to 1)
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
        lo, hi, q = parameter["min"], parameter["max"], parameter["q"]
        # q_uniform is produced from both Int and Float stepped distributions;
        # pick the int variant only when every bound is integral.
        if _is_int(lo) and _is_int(hi) and _is_int(q):
            return distributions.IntDistribution(lo, hi, step=q)
        return distributions.FloatDistribution(lo, hi, step=q)

    if dist == "q_log_uniform_values":
        # optuna forbids step+log on floats, so this maps to a log-scale int
        # space.
        return distributions.IntDistribution(
            parameter["min"],
            parameter["max"],
            log=True,
            step=int(parameter.get("q", 1)),
        )

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

        super().__init__(sweep)

    @property
    def _is_multi_objective(self) -> bool:
        """Whether the study optimizes more than one objective."""
        return len(self.study.directions) > 1

    def metric_names(self) -> list[str]:
        """Return the sweep's objective metric names, in the study's order.

        A multi-objective sweep names them in `metrics`; a single-objective
        one in `metric`.
        """
        metrics = self._sweep.config.get("metrics")
        if metrics is not None:
            return [metric["name"] for metric in metrics if "name" in metric]
        return [self.metric_key()]

    def _objective_values(self, metrics: dict[str, Any]) -> list[Any] | None:
        """Return a run's objective values, or None if any is missing.

        Args:
            metrics: The run's summary metrics.
        """
        values = [metrics.get(name) for name in self.metric_names()]
        if any(value is None for value in values):
            return None
        return values

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
            values = self._objective_values(data.summary_metrics)
            if values is None:
                # A run that finished without every objective taught the
                # search nothing; record a failure rather than telling the
                # study a missing value.
                self.study.tell(trial, state=optuna.trial.TrialState.FAIL)
            elif self._is_multi_objective:
                self.study.tell(trial, values, state=state)
            else:
                self.study.tell(trial, values[0], state=state)
        elif state == optuna.trial.TrialState.FAIL:
            self.study.tell(trial, state=state)
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
        self.study.tell(trial, state=optuna.trial.TrialState.FAIL)

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
        self.study.tell(trial, state=optuna.trial.TrialState.PRUNED)
        del self.trials[run_id]
        self._last_reported_step.pop(run_id, None)
        return True

    @override
    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an in-flight run by recreating a live trial for its params.

        Enqueuing the run's params makes the next ask() (via ask_n_runs, which
        also handles the imperative conditional branch) return a trial fixed to
        them. The trial is left RUNNING — not told — so the loop reports its
        intermediate values for pruning and finalizes it via tell_run when the
        run completes.

        Returns:
            The trial number to track the run by, or None if the study
            produced no trial for the enqueued params.
        """
        self.study.enqueue_trial(data.config.flat_dict())
        runs = self.ask_n_runs(1)
        return runs[0].run_id if runs else None


class OptunaDeclarativeOptimizer(OptunaOptimizer):
    """Define-and-run: the space is supplied up front as distributions.

    The distributions are known before any trial runs, so the sweep is built
    directly from them and `ask_n_runs` samples by passing them to `study.ask`.
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
    def ask_n_runs(self, n: int) -> Sequence[RunSuggestion]:
        """Sample `n` trials from the declared distributions."""
        suggestions = []
        for _ in range(n):
            trial = self.study.ask(self.distributions)
            self.trials[str(trial.number)] = trial
            suggestions.append(
                RunSuggestion(
                    config=RunConfig.from_values(trial.params),
                    run_id=str(trial.number),
                )
            )
        return suggestions

    @override
    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        """Warm-start the study by recording a run as a historical trial.

        The flat search space is known up front, so add_trial() is the lightest
        faithful path — no extra ask(). Runs whose config doesn't cover the
        search space are skipped (create_trial requires an exact param match).
        """
        if not is_terminal_state(data.state):
            return
        trial_state = self.trial_state(data.state)  # COMPLETE or FAIL
        values = None
        if trial_state == optuna.trial.TrialState.COMPLETE:
            values = self._objective_values(data.summary_metrics)
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
            )
        )


class OptunaImperativeOptimizer(OptunaOptimizer):
    """Define-by-run: the space is discovered by a TrialConstructor.

    The constructor's `trial.suggest_*` calls implicitly define the space. We
    run it once against a throwaway trial to record the distributions, build the
    sweep from them, then re-run it for real suggestions in `ask_n_runs`.
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
    def ask_n_runs(self, n: int) -> Sequence[RunSuggestion]:
        """Sample `n` trials, running the constructor on each."""
        suggestions = []
        for _ in range(n):
            trial = self.study.ask()
            # A define-by-run constructor returns the flat {param: value}
            # mapping.
            params = self.trial_constructor(trial)
            self.trials[str(trial.number)] = trial
            # run_id is str(trial.number), so tell_run can look up the trial.
            suggestions.append(
                RunSuggestion(
                    config=RunConfig.from_values(params), run_id=str(trial.number)
                )
            )
        return suggestions

    @override
    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        """Warm-start the study by replaying a run through the constructor.

        Enqueuing the run's params makes the next ask() take the same (possibly
        conditional) branch, so the recreated trial's distributions match the
        run; tell_run then finalizes it on the study.
        """
        if not is_terminal_state(data.state):
            return
        # A finished run with no objective value would make tell_run pass None
        # to a COMPLETE study.tell(), so skip it.
        if (
            data.state == RunState.FINISHED
            and self._objective_values(data.summary_metrics) is None
        ):
            return
        self.study.enqueue_trial(data.config.flat_dict(), skip_if_exists=True)
        suggestions = list(self.ask_n_runs(1))
        if not suggestions:
            return
        self.tell_run(suggestions[0].run_id, data)


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
    if metrics is not None:
        directions = [str(metric.get("goal", "minimize")).lower() for metric in metrics]
        return optuna.create_study(directions=directions)
    goal = (config.get("metric") or {}).get("goal", "minimize")
    return optuna.create_study(direction=goal)


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
