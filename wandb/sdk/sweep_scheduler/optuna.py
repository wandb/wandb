from __future__ import annotations

from wandb.sdk.sweep_scheduler.optimizer import Optimizer, Run, RunConfig, RunSuggestion, RunEnriched, terminal_state
from wandb.sdk.sweep_scheduler.scheduler import Executor, InMemoryScheduler, Scheduler, scheduler_sweep_config
from wandb.apis.public import Sweep
from wandb import util, sweep as wandb_sweep, Api
from typing import Any, Callable, Iterable, TypeAlias
from wandb.sdk.launch.sweeps.scheduler import RunState

optuna = util.get_module(
    "optuna",
    required="wandb[optuna] is required to use the Optuna sweep scheduler. "
    "Please run `pip install wandb[optuna]`.",
)

TrialConstructor: TypeAlias = Callable[["optuna.Trial"], RunSuggestion]


def distribution_to_sweep_parameter(
    dist: "optuna.distributions.BaseDistribution",
) -> dict[str, Any]:
    """Convert a single optuna distribution into a W&B sweep config parameter spec.

    The returned dict is the value for one entry under a sweep config's
    ``parameters`` block (e.g. ``{"distribution": "uniform", "min": 0, "max": 1}``).
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


def sweep_parameter_to_distribution(
    parameter: dict[str, Any],
) -> "optuna.distributions.BaseDistribution":
    """Convert a single W&B sweep config parameter spec into an optuna distribution.

    Inverse of `distribution_to_sweep_parameter`. optuna only models float, int and
    categorical spaces, so sweep distributions without an optuna equivalent (normal,
    beta, inv_log_uniform, exponent-space log_uniform, ...) raise ValueError.
    """
    distributions = optuna.distributions

    # Constant / categorical shorthands — the `distribution` key is optional in W&B.
    if "value" in parameter:
        return distributions.CategoricalDistribution([parameter["value"]])
    if "values" in parameter and "distribution" not in parameter:
        return distributions.CategoricalDistribution(list(parameter["values"]))

    dist = parameter.get("distribution")
    if dist is None:
        # No explicit distribution: W&B infers int_uniform vs uniform from min/max.
        if "min" in parameter and "max" in parameter:
            lo, hi = parameter["min"], parameter["max"]
            dist = "int_uniform" if _is_int(lo) and _is_int(hi) else "uniform"
        else:
            raise ValueError(
                f"Cannot infer an optuna distribution from sweep parameter: {parameter!r}"
            )

    if dist in ("categorical", "constant"):
        if "values" in parameter:
            return distributions.CategoricalDistribution(list(parameter["values"]))
        return distributions.CategoricalDistribution([parameter["value"]])

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
        # q_uniform is produced from both Int and Float stepped distributions; pick
        # the int variant only when every bound is integral.
        if _is_int(lo) and _is_int(hi) and _is_int(q):
            return distributions.IntDistribution(lo, hi, step=q)
        return distributions.FloatDistribution(lo, hi, step=q)

    if dist == "q_log_uniform_values":
        # optuna forbids step+log on floats, so this maps to a log-scale int space.
        return distributions.IntDistribution(
            parameter["min"], parameter["max"], log=True, step=int(parameter.get("q", 1))
        )

    raise ValueError(
        f"Sweep distribution {dist!r} has no optuna equivalent and cannot be converted."
    )


def search_space_from_sweep_config(
    parameters: dict[str, Any],
) -> dict[str, "optuna.distributions.BaseDistribution"]:
    """Convert a sweep config's ``parameters`` block (name -> spec) into an optuna
    search space (name -> distribution)."""
    return {
        name: sweep_parameter_to_distribution(spec)
        for name, spec in parameters.items()
    }


def sweep_from_study(
    study: optuna.Study,
    search_space: dict[str, "optuna.distributions.BaseDistribution"],
    entity: str,
    project: str,
    metric_name: str,
    program_path: str | None = None,
) -> Sweep:
    """Create a W&B sweep mirroring an optuna study's search space and direction.

    The study's optimization direction is mapped onto the sweep metric's goal
    (``minimize`` / ``maximize``); ``metric_name`` names the metric that runs log
    and that the optimizer reads back when telling the study. ``program_path``, if
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
        **scheduler_sweep_config,
    }
    if program_path is not None:
        config["program"] = program_path

    sid = wandb_sweep(config, entity=entity, project=project)
    return Api().sweep(f"{entity}/{project}/{sid}")


class OptunaOptimizer(Optimizer):
    def __init__(
        self,
        study: optuna.Study,
        sweep: Sweep,
    ):
        super().__init__(sweep)
        self.study = study
        # Live ask()'d trials kept by trial.number. The study only stores frozen
        # trials, which lack report()/should_prune(), so we must hold the live
        # ones to record intermediate values (and, next, drive pruning).
        self.trials: dict[int, "optuna.Trial"] = {}
        self._validate_matches_sweep()

    def _validate_matches_sweep(self) -> None:
        """Fail fast if the study and the sweep disagree on the objective.

        The study's optimization direction must match the sweep metric's goal,
        and — when the study declares metric names — its objective name must match
        the sweep metric's name. Otherwise the optimizer would silently search the
        wrong way or against the wrong metric. The study and sweep are supplied
        independently (e.g. via `resume_sweep` or a user-provided study factory),
        so the two can drift; the sweep config is the source of truth.
        """
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

        # optuna's objective names are optional metadata; validate only when set.
        metric_names = getattr(self.study, "metric_names", None)
        if metric_names:
            metric_name = self.metric_key()
            if metric_names[0] != metric_name:
                raise ValueError(
                    f"Study metric name {metric_names[0]!r} does not match the "
                    f"sweep metric name {metric_name!r}."
                )

    def trial_state(self, state: RunState) -> optuna.trial.TrialState:
        if state in (RunState.RUNNING, RunState.PENDING):
            return optuna.trial.TrialState.RUNNING
        elif state == RunState.FINISHED:
            return optuna.trial.TrialState.COMPLETE
        elif state in (RunState.FAILED, RunState.CRASHED, RunState.KILLED):
            return optuna.trial.TrialState.FAIL
        else:
            raise ValueError(f"Unknown trial state: {state}")

    def tell_run(self, run_id: Any, data: RunEnriched) -> None:
        # run_id is the optuna trial.number set in next_n_runs.
        trial = self.trials[run_id]
        for row in data.history_metrics:
            value = self.metric_value(row)
            if value is not None:
                trial.report(value, step=row["_step"])

        state = self.trial_state(data.state)
        if state == optuna.trial.TrialState.COMPLETE:
            self.study.tell(trial, self.metric_value(data.summary_metrics), state=state)
        elif state == optuna.trial.TrialState.FAIL:
            self.study.tell(trial, state=state)
        # RUNNING: only intermediate values are reported; the trial is finalized
        # later (on completion/failure) or by prune_run.

    def prune_run(self, run_id: Any, data: RunEnriched) -> bool:
        # tell_run already reported this poll's intermediate values, so the study's
        # pruner can decide. On a prune, finalize the trial as PRUNED.
        trial = self.trials[run_id]
        if not trial.should_prune():
            return False
        self.study.tell(trial, state=optuna.trial.TrialState.PRUNED)
        return True

    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an in-flight run by recreating a live trial bound to its params.

        Enqueuing the run's params makes the next ask() (via next_n_runs, which
        also handles the imperative conditional branch) return a trial fixed to
        them. The trial is left RUNNING — not told — so the loop reports its
        intermediate values for pruning and finalizes it via tell_run when the
        run completes. Returns the trial number to track the run by.
        """
        self.study.enqueue_trial(data.config)
        suggestions = list(self.next_n_runs(1))
        if not suggestions:
            return None
        return suggestions[0].run_id


class OptunaDeclarativeOptimizer(OptunaOptimizer):
    """Define-and-run: the search space is supplied up front as optuna distributions.

    The distributions are known before any trial runs, so the sweep is built
    directly from them and `next_n_runs` samples by passing them to `study.ask`.
    """

    def __init__(
        self,
        study: optuna.Study,
        distributions: dict[str, "optuna.distributions.BaseDistribution"],
        sweep: Sweep,
    ):
        self.distributions = distributions
        super().__init__(study, sweep)

    def next_n_runs(self, n: int) -> Iterable[RunSuggestion]:
        suggestions = []
        for _ in range(n):
            trial = self.study.ask(self.distributions)
            self.trials[trial.number] = trial
            suggestions.append(
                RunSuggestion(
                    config=RunConfig.from_values(trial.params), run_id=trial.number
                )
            )
        return suggestions

    def tell_existing_finished_run(self, data: RunEnriched) -> None:
        """Warm-start the study by recording an existing run as a historical trial.

        The flat search space is known up front, so add_trial() is the lightest
        faithful path — no extra ask(). Runs whose config doesn't cover the
        search space are skipped (create_trial requires an exact param match).
        """
        run_state = terminal_state(data.state)
        if run_state is None:
            return
        trial_state = self.trial_state(run_state)  # COMPLETE or FAIL
        value = None
        if trial_state == optuna.trial.TrialState.COMPLETE:
            value = self.metric_value(data.summary_metrics)
            if value is None:
                return  # finished but never logged the objective metric
        if not all(name in data.config for name in self.distributions):
            return
        params = {name: data.config[name] for name in self.distributions}
        self.study.add_trial(
            optuna.trial.create_trial(
                params=params,
                distributions=self.distributions,
                value=value,
                state=trial_state,
            )
        )


class OptunaImperativeOptimizer(OptunaOptimizer):
    """Define-by-run: the search space is discovered by running a TrialConstructor.

    The constructor's `trial.suggest_*` calls implicitly define the space. We run
    it once against a throwaway trial to record the distributions, build the sweep
    from them, then re-run it for real suggestions in `next_n_runs`.
    """

    def __init__(
        self,
        study: optuna.Study,
        trial_constructor: TrialConstructor,
        sweep: Sweep,
    ):
        self.trial_constructor = trial_constructor
        super().__init__(study, sweep)

    def next_n_runs(self, n: int) -> Iterable[RunSuggestion]:
        suggestions = []
        for _ in range(n):
            trial = self.study.ask()
            suggestion = self.trial_constructor(trial)
            self.trials[trial.number] = trial
            # run_id is trial.number so tell_run can look up the live trial.
            suggestions.append(
                RunSuggestion(config=suggestion.config, run_id=trial.number)
            )
        return suggestions

    def tell_existing_finished_run(self, data: RunEnriched) -> None:
        """Warm-start the study by replaying an existing run through the trial
        constructor. Enqueuing the run's params makes the next ask() take the same
        (possibly conditional) branch, so the recreated trial's distributions match
        the run; tell_run then finalizes it on the study.
        """
        run_state = terminal_state(data.state)
        if run_state is None:
            return
        # A finished run with no objective value would make tell_run pass None to
        # a COMPLETE study.tell(), so skip it.
        if run_state == RunState.FINISHED and self.metric_value(data.summary_metrics) is None:
            return
        self.study.enqueue_trial(data.config, skip_if_exists=True)
        suggestions = list(self.next_n_runs(1))
        if not suggestions:
            return
        self.tell_run(suggestions[0].run_id, data)


# ---------------------------------------------------------------------------
# Public entry points.
#
# These free functions are the supported way to build a scheduler; callers
# should not instantiate the optimizer classes directly. Each returns a
# Scheduler whose `.loop()` drives the sweep. The flavor (define-and-run
# vs define-by-run) is chosen by which of `distributions` or `trial_constructor`
# is supplied.
# ---------------------------------------------------------------------------


def _spy_search_space(
    study: optuna.Study,
    trial_constructor: TrialConstructor,
) -> dict[str, "optuna.distributions.BaseDistribution"]:
    """Discover an imperative search space by running the constructor against a
    throwaway trial and reading back the distributions its `suggest_*` calls
    registered.

    A separate in-memory study is used so the real study isn't polluted with the
    spy trial; we only need `Trial.distributions`, not the sampled values. Note a
    single spy trial only captures the branch taken for a conditional space.
    """
    spy_study = optuna.create_study(directions=study.directions)
    spy_trial = spy_study.ask()
    trial_constructor(spy_trial)
    return spy_trial.distributions


def _make_optimizer(
    study: optuna.Study,
    sweep: Sweep,
    distributions: dict[str, "optuna.distributions.BaseDistribution"] | None,
    trial_constructor: TrialConstructor | None,
) -> OptunaOptimizer:
    if (distributions is None) == (trial_constructor is None):
        raise ValueError(
            "provide exactly one of `distributions` or `trial_constructor`"
        )
    if distributions is not None:
        return OptunaDeclarativeOptimizer(study, distributions, sweep)
    return OptunaImperativeOptimizer(study, trial_constructor, sweep)


def resume_sweep(
    study: optuna.Study,
    sweep: Sweep | str,
    *,
    distributions: dict[str, "optuna.distributions.BaseDistribution"] | None = None,
    trial_constructor: TrialConstructor | None = None,
    poll_interval_s: float = 5.0,
    batch_size: int = 1,
    executor: Callable[[Sweep], Executor] | None = None,
) -> Scheduler:
    """Attach a scheduler to a sweep that already exists.

    `sweep` may be a `Sweep` or an "entity/project/sweep_id" path string. Pass
    exactly one of `distributions` (define-and-run) or `trial_constructor`
    (define-by-run) to choose how the study samples. `executor` is a factory taking
    the resolved sweep and returning the backend that schedules runs (defaults to
    the W&B run queue).
    """
    if isinstance(sweep, str):
        sweep = Api().sweep(sweep)
    optimizer = _make_optimizer(study, sweep, distributions, trial_constructor)
    return InMemoryScheduler(
        optimizer,
        sweep,
        poll_interval_s,
        batch_size,
        executor(sweep) if executor is not None else None,
    )


def create_sweep(
    study: optuna.Study,
    entity: str,
    project: str,
    metric_name: str,
    *,
    distributions: dict[str, "optuna.distributions.BaseDistribution"] | None = None,
    trial_constructor: TrialConstructor | None = None,
    poll_interval_s: float = 5.0,
    batch_size: int = 1,
    program_path: str | None = None,
    executor: Callable[[Sweep], Executor] | None = None,
) -> Scheduler:
    """Create a new sweep from the study's search space, then attach a scheduler.

    Pass exactly one of `distributions` (define-and-run) or `trial_constructor`
    (define-by-run); the latter's search space is discovered by running it once to
    build the sweep. `executor` is a factory taking the created sweep and returning
    the backend that schedules runs (defaults to the W&B run queue).
    """
    if (distributions is None) == (trial_constructor is None):
        raise ValueError(
            "provide exactly one of `distributions` or `trial_constructor`"
        )
    search_space = (
        distributions
        if distributions is not None
        else _spy_search_space(study, trial_constructor)
    )
    sweep = sweep_from_study(
        study, search_space, entity, project, metric_name, program_path
    )
    optimizer = _make_optimizer(study, sweep, distributions, trial_constructor)
    return InMemoryScheduler(
        optimizer,
        sweep,
        poll_interval_s,
        batch_size,
        executor(sweep) if executor is not None else None,
    )


def create_sweep_from_config(
    config: dict[str, Any],
    entity: str,
    project: str,
    *,
    study: optuna.Study | None = None,
    poll_interval_s: float = 5.0,
    batch_size: int = 1,
    executor: Callable[[Sweep], Executor] | None = None,
) -> Scheduler:
    """Create the study, the sweep and a scheduler from a sweep config alone.

    The search space is derived from `config["parameters"]` and, when no study is
    supplied, the study's direction from `config["metric"]["goal"]`, so the caller
    only needs a sweep config. The local scheduler requires a custom method, so
    `scheduler_sweep_config` is merged in (overriding `method`). `executor` is a
    factory taking the created sweep and returning the backend that schedules runs
    (defaults to the W&B run queue).
    """
    distributions = search_space_from_sweep_config(config.get("parameters", {}))
    if study is None:
        goal = config.get("metric", {}).get("goal", "minimize")
        study = optuna.create_study(direction=goal)
    sweep_id = wandb_sweep(
        {**config, **scheduler_sweep_config}, entity=entity, project=project
    )
    sweep = Api().sweep(f"{entity}/{project}/{sweep_id}")
    optimizer = OptunaDeclarativeOptimizer(study, distributions, sweep)
    return InMemoryScheduler(
        optimizer,
        sweep,
        poll_interval_s,
        batch_size,
        executor(sweep) if executor is not None else None,
    )
