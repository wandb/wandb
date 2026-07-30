from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias

from typing_extensions import override

from wandb import Api, util
from wandb import sweep as wandb_sweep
from wandb.apis.public import Sweep
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.optimizer import (
    Optimizer,
    Run,
    RunConfig,
    RunSuggestion,
    RunWithMetrics,
    is_terminal_state,
)
from wandb.sdk.sweeps.scheduler.scheduler import (
    InMemoryScheduler,
    Scheduler,
    SchedulerOptions,
)

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
class OptunaOptions(SchedulerOptions):
    """Scheduler and optuna settings for building or resuming a sweep.

    `poll_interval_s`, `batch_size` and `executor` are inherited from
    `SchedulerOptions`.

    `study` is required by `resume_sweep`/`create_sweep`;
    `create_sweep_from_config` builds one from the config's metric goal(s)
    when left `None`, and always derives `distributions` from the config
    itself, ignoring `distributions`/`search_space` here. Pass exactly one
    of `distributions` (define-and-run) or `search_space` (define-by-run)
    to choose how `study` samples.

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


def distribution_to_sweep_parameter(
    dist: optuna.distributions.BaseDistribution,
) -> dict[str, Any]:
    """Convert an optuna distribution into a W&B sweep parameter spec.

    The returned dict is the value for one entry under a sweep config's
    `parameters` block (e.g. `{"distribution": "uniform", "min": 0, "max": 1}`).

    Inverse of `sweep_parameter_to_distribution`. The mapping is:

    - `CategoricalDistribution(choices)` -> `{"values": choices}`
    - `IntDistribution(log=True)` -> `q_log_uniform_values` with `q=step`
      (W&B has no log-scale int distribution; this samples log-uniform in
      value space and rounds to multiples of `q`)
    - `IntDistribution(step != 1)` -> `q_uniform` with `q=step`
    - `IntDistribution` otherwise -> `int_uniform`
    - `FloatDistribution(log=True)` -> `log_uniform_values` (optuna forbids
      `step` together with `log`, so there is no q-variant)
    - `FloatDistribution(step is not None)` -> `q_uniform` with `q=step`
    - `FloatDistribution` otherwise -> `uniform`

    Numeric specs carry `min`/`max` from the distribution's `low`/`high`.
    Any other distribution type raises `TypeError`.
    """
    distributions = optuna.distributions

    if isinstance(dist, distributions.CategoricalDistribution):
        # W&B infers a categorical parameter from a `values` list.
        return {"values": list(dist.choices)}

    if isinstance(dist, distributions.IntDistribution):
        if dist.log:
            # No native int-log in W&B; sample log-uniform in value space and
            # round to multiples of `step` (defaults to 1).
            return {
                "distribution": "q_log_uniform_values",
                "min": dist.low,
                "max": dist.high,
                "q": dist.step,
            }
        if dist.step != 1:
            return {
                "distribution": "q_uniform",
                "min": dist.low,
                "max": dist.high,
                "q": dist.step,
            }
        return {"distribution": "int_uniform", "min": dist.low, "max": dist.high}

    if isinstance(dist, distributions.FloatDistribution):
        if dist.log:
            # optuna disallows `step` together with `log`, so no q-variant here.
            return {
                "distribution": "log_uniform_values",
                "min": dist.low,
                "max": dist.high,
            }
        if dist.step is not None:
            return {
                "distribution": "q_uniform",
                "min": dist.low,
                "max": dist.high,
                "q": dist.step,
            }
        return {"distribution": "uniform", "min": dist.low, "max": dist.high}

    raise TypeError(
        f"Cannot convert optuna distribution to a sweep parameter: "
        f"{type(dist).__name__} is not supported."
    )


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

    Inverse of `distribution_to_sweep_parameter`. The mapping, by the spec's
    `distribution` name, is:

    - `categorical` / `constant`, or a bare `value`/`values` spec with no
      `distribution` key -> `CategoricalDistribution`
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


def sweep_from_study(
    study: optuna.Study,
    search_space: dict[str, optuna.distributions.BaseDistribution],
    entity: str,
    project: str,
    metric_name: str,
    program_path: str | None = None,
) -> Sweep:
    """Create a W&B sweep mirroring an optuna study's space and direction.

    The study's optimization direction is mapped onto the sweep metric's goal
    (`minimize` / `maximize`); `metric_name` names the metric that runs log and
    that the optimizer reads back when telling the study. `program_path`, if
    given, sets the sweep's training program.
    """
    if len(study.directions) != 1:
        raise ValueError(
            "sweep_from_study only supports single-objective studies; "
            f"got {len(study.directions)} objectives."
        )

    config: dict[str, Any] = {
        "metric": {
            "name": metric_name,
            # StudyDirection.MINIMIZE/MAXIMIZE -> "minimize"/"maximize".
            "goal": study.direction.name.lower(),
        },
        "parameters": {
            name: distribution_to_sweep_parameter(dist)
            for name, dist in search_space.items()
        },
        "scheduler": {
            "engine": "optuna",
        },
    }
    if program_path is not None:
        config["program"] = program_path

    sid = wandb_sweep(config, entity=entity, project=project)
    return Api().sweep(f"{entity}/{project}/{sid}")


class OptunaOptimizer(Optimizer):
    """Base `Optimizer` driving a W&B sweep from an optuna study.

    Subclasses supply the search space, either up front as distributions or by
    running a define-by-run constructor.
    """

    @override
    def __init__(
        self,
        study: optuna.Study,
        sweep: Sweep,
        terminator: TerminatorCallback | None = None,
    ):
        super().__init__(sweep)
        self.study = study
        # Live ask()'d trials kept by str(trial.number). The study only
        # stores frozen trials, which lack report()/should_prune(), so we
        # must hold the live ones to record intermediate values (and, next,
        # drive pruning).
        self.trials: dict[str, optuna.Trial] = {}
        self._validate_matches_sweep()
        self._terminator = terminator

    @override
    def should_terminate_sweep(self) -> bool:
        """Return True once the caller's `terminator` says the search is done.

        `terminator` is supplied via `OptunaOptions`; the default is `None`,
        which never terminates early.
        """
        return self._terminator is not None and self._terminator(self.study)

    def _validate_matches_sweep(self) -> None:
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
        """Map a sweep `RunState` onto the optuna `TrialState` it stands for."""
        if state in (RunState.RUNNING, RunState.PENDING):
            return optuna.trial.TrialState.RUNNING
        if state == RunState.FINISHED:
            return optuna.trial.TrialState.COMPLETE
        if state in (RunState.FAILED, RunState.CRASHED, RunState.KILLED):
            return optuna.trial.TrialState.FAIL
        raise ValueError(f"Unknown trial state: {state}")

    @override
    def tell_run(self, run_id: Any, data: RunWithMetrics) -> None:
        """Report a run's intermediate values and finalize it once terminal."""
        # run_id is str(trial.number), set in ask_n_runs.
        trial = self.trials[run_id]
        for step, row in enumerate(data.history_metrics):
            value = self.metric_value(row)
            if value is not None:
                trial.report(value, step=row.get("_step", step))

        state = self.trial_state(data.state)
        if state == optuna.trial.TrialState.COMPLETE:
            self.study.tell(trial, self.metric_value(data.summary_metrics), state=state)
        elif state == optuna.trial.TrialState.FAIL:
            self.study.tell(trial, state=state)
        # RUNNING: only intermediate values are reported; the trial is finalized
        # later (on completion/failure) or by prune_run.

    @override
    def prune_run(self, run_id: Any, data: RunWithMetrics) -> bool:
        """Return True if the study's pruner says the run should stop early."""
        # tell_run already reported this poll's intermediate values, so the
        # study's pruner can decide. On a prune, finalize the trial as PRUNED.
        trial = self.trials[run_id]
        if not trial.should_prune():
            return False
        self.study.tell(trial, state=optuna.trial.TrialState.PRUNED)
        return True

    @override
    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an in-flight run by recreating a live trial for its params.

        Enqueuing the run's params makes the next ask() (via ask_n_runs, which
        also handles the imperative conditional branch) return a trial fixed to
        them. The trial is left RUNNING — not told — so the loop reports its
        intermediate values for pruning and finalizes it via tell_run when the
        run completes. Returns the trial number to track the run by.
        """
        self.study.enqueue_trial(data.config.flat_dict())
        suggestions = list(self.ask_n_runs(1))
        if not suggestions:
            return None
        return suggestions[0].run_id


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
        sweep: Sweep,
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
        value = None
        if trial_state == optuna.trial.TrialState.COMPLETE:
            value = self.metric_value(data.summary_metrics)
            if value is None:
                return  # finished but never logged the objective metric
        config = data.config.flat_dict()
        if not all(name in config for name in self.distributions):
            return
        params = {name: config[name] for name in self.distributions}
        self.study.add_trial(
            optuna.trial.create_trial(
                params=params,
                distributions=self.distributions,
                value=value,
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
        sweep: Sweep,
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
            and self.metric_value(data.summary_metrics) is None
        ):
            return
        self.study.enqueue_trial(data.config.flat_dict(), skip_if_exists=True)
        suggestions = list(self.ask_n_runs(1))
        if not suggestions:
            return
        self.tell_run(suggestions[0].run_id, data)


# ---------------------------------------------------------------------------
# Public entry points.
#
# These free functions are the supported way to build a scheduler; callers
# should not instantiate the optimizer classes directly. Each returns a
# Scheduler whose `.loop()` drives the sweep. The flavor (define-and-run
# vs define-by-run) is chosen by which of `distributions` or `search_space`
# is supplied.
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


def _spy_search_space(
    study: optuna.Study,
    trial_constructor: TrialConstructor,
) -> dict[str, optuna.distributions.BaseDistribution]:
    """Discover an imperative search space by spying on a throwaway trial.

    The constructor is run against that trial and the distributions its
    `suggest_*` calls registered are read back.

    A separate in-memory study is used so the real study isn't polluted with the
    spy trial; we only need `Trial.distributions`, not the sampled values. Note
    a single spy trial only captures the branch taken for a conditional space.
    """
    spy_study = optuna.create_study(directions=study.directions)
    spy_trial = spy_study.ask()
    trial_constructor(spy_trial)
    return spy_trial.distributions


def _make_optimizer(
    study: optuna.Study, sweep: Sweep, options: OptunaOptions
) -> OptunaOptimizer:
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


def resume_sweep(
    sweep: Sweep | str,
    *,
    options: OptunaOptions | None = None,
) -> Scheduler:
    """Attach a scheduler to a sweep that already exists.

    `sweep` may be a `Sweep` or an "entity/project/sweep_id" path string.
    `options.study` is required, and exactly one of `options.distributions`
    (define-and-run) or `options.search_space` (define-by-run) chooses how
    the study samples.
    """
    resolved_sweep: Sweep = Api().sweep(sweep) if isinstance(sweep, str) else sweep
    options = options or OptunaOptions()
    if options.study is None:
        raise ValueError("`options.study` is required")
    built_optimizer = _make_optimizer(options.study, resolved_sweep, options)
    return InMemoryScheduler(
        built_optimizer,
        resolved_sweep,
        options,
    )


def create_sweep(
    entity: str,
    project: str,
    metric_name: str,
    *,
    program_path: str | None = None,
    options: OptunaOptions | None = None,
) -> Scheduler:
    """Create a sweep from the study's search space, then attach a scheduler.

    `options.study` is required. Pass exactly one of `options.distributions`
    (define-and-run) or `options.search_space` (define-by-run); the latter's
    search space is discovered by running it once to build the sweep.
    """
    options = options or OptunaOptions()
    if options.study is None:
        raise ValueError("`options.study` is required")
    if (options.distributions is None) == (options.search_space is None):
        raise ValueError("provide exactly one of `distributions` or `search_space`")
    if options.distributions is not None:
        resolved_space = options.distributions
    else:
        assert options.search_space is not None  # guaranteed by the check above
        resolved_space = _spy_search_space(options.study, options.search_space)
    sweep = sweep_from_study(
        options.study, resolved_space, entity, project, metric_name, program_path
    )
    return resume_sweep(sweep, options=options)


def create_sweep_from_config(
    config: dict[str, Any],
    entity: str,
    project: str,
    *,
    options: OptunaOptions | None = None,
) -> Scheduler:
    """Create the study, the sweep and a scheduler from a sweep config alone.

    The search space is derived from `config["parameters"]`, ignoring
    `options.distributions`/`options.search_space`. When `options.study` is
    `None`, a study is built from `config["metric"]` or `config["metrics"]`, so
    the caller only needs a sweep config.
    """
    distributions = search_space_from_sweep_config(config.get("parameters", {}))
    options = options or OptunaOptions()
    study = options.study
    if study is None:
        study = create_study_from_sweep_config(config)
    sweep_id = wandb_sweep(config, entity=entity, project=project)
    sweep = Api().sweep(f"{entity}/{project}/{sweep_id}")
    optimizer = OptunaDeclarativeOptimizer(
        study, distributions, sweep, options.terminator
    )
    return InMemoryScheduler(
        optimizer,
        sweep,
        options,
    )
