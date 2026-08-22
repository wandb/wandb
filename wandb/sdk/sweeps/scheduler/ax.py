from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

from typing_extensions import override

from wandb import sweep as wandb_sweep
from wandb import util
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.client import SchedulerOptions, run_scheduler
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
    # Only used for static type checking, so referencing ax's types below
    # doesn't force a real import at runtime for users who never touch this
    # scheduler.
    import ax
else:
    ax = util.get_module(
        "ax",
        required="wandb[ax] is required to use the Ax sweep scheduler. "
        "Please run `pip install wandb[ax]`.",
    )

TerminatorCallback: TypeAlias = Callable[["ax.Client"], bool]


@dataclass
class AxOptions(SchedulerOptions):
    """Scheduler and Ax settings for building or resuming a sweep.

    `poll_interval_s` and `batch_size` are inherited from
    `SchedulerOptions`.

    `client` is required by `resume_sweep`/`create_sweep`: the Ax `Client`
    owning the experiment (search space + objective) this scheduler drives.

    `terminator` decides when the search itself is exhausted -- any custom
    stopping rule the caller wants. It is the caller's own callback: nothing
    is loaded or configured on their behalf. The default `None` never
    terminates early.
    """

    client: ax.Client | None = None
    terminator: TerminatorCallback | None = None


def parameter_to_sweep_parameter(parameter: Any) -> dict[str, Any]:
    """Convert an Ax (core) parameter into a W&B sweep parameter spec.

    `parameter` is one of the experiment's live parameters (e.g. an
    `ax.core.parameter.RangeParameter`), as read from the search space of
    the client's configured experiment. The returned dict is the value
    for one entry under a sweep config's `parameters` block (e.g.
    `{"distribution": "uniform", "min": 0, "max": 1}`).

    Inverse of `sweep_parameter_to_parameter`. The mapping is:

    - `ChoiceParameter(values)` -> `{"values": values}`
    - `FixedParameter(value)` -> `{"value": value}`
    - int `RangeParameter` with `log_scale` -> `q_log_uniform_values` with
      `q=1` (W&B has no log-scale int distribution; this samples log-uniform
      in value space and rounds to integers)
    - int `RangeParameter` otherwise -> `int_uniform`
    - float `RangeParameter` with `log_scale` -> `log_uniform_values`
    - float `RangeParameter` otherwise -> `uniform`

    Range specs carry `min`/`max` from the parameter's `lower`/`upper`.
    Any other parameter type raises `TypeError`.
    """
    # Ax's core parameter classes aren't exported at the top level, so import
    # them here (ax is guaranteed installed once this module imports).
    from ax.core.parameter import ChoiceParameter, FixedParameter, RangeParameter

    if isinstance(parameter, RangeParameter):
        low, high = parameter.lower, parameter.upper
        if parameter.parameter_type.name == "INT":
            if parameter.log_scale:
                # W&B has no native int-log; sample log-uniform in value space
                # and round to integers (q=1), matching the optuna scheduler.
                return {
                    "distribution": "q_log_uniform_values",
                    "min": low,
                    "max": high,
                    "q": 1,
                }
            return {"distribution": "int_uniform", "min": low, "max": high}
        if parameter.log_scale:
            return {"distribution": "log_uniform_values", "min": low, "max": high}
        return {"distribution": "uniform", "min": low, "max": high}

    if isinstance(parameter, ChoiceParameter):
        # W&B infers a categorical parameter from a `values` list.
        return {"values": list(parameter.values)}

    if isinstance(parameter, FixedParameter):
        # A single constant value.
        return {"value": parameter.value}

    raise TypeError(
        f"Cannot convert Ax parameter to a sweep parameter: "
        f"{type(parameter).__name__} is not supported."
    )


def search_space_to_sweep_parameters(
    search_space: Any,
) -> dict[str, dict[str, Any]]:
    """Convert an Ax search space into a sweep config `parameters` block.

    Maps each of the search space's `name -> parameter` entries onto a
    `name -> spec` entry via `parameter_to_sweep_parameter`. Inverse of
    `sweep_parameters_to_search_space`.
    """
    return {
        name: parameter_to_sweep_parameter(parameter)
        for name, parameter in search_space.parameters.items()
    }


def _is_int(value: Any) -> bool:
    # bool is a subclass of int but is never a numeric bound/choice here.
    return isinstance(value, int) and not isinstance(value, bool)


def _value_type(values: list[Any]) -> Literal["bool", "int", "float", "str"]:
    """Infer the Ax `parameter_type` for a set of categorical / constant values.

    Returns one of `"bool"` / `"int"` / `"float"` / `"str"` — the strings
    Ax's `ChoiceParameterConfig` expects.
    """
    if values and all(isinstance(v, bool) for v in values):
        return "bool"
    if values and all(_is_int(v) for v in values):
        return "int"
    if values and all(isinstance(v, (int, float)) for v in values):
        return "float"
    return "str"


def _choice_config(name: str, values: list[Any]) -> Any:
    """Build an Ax `ChoiceParameterConfig` from W&B `values`.

    A single-value list becomes a fixed parameter (Ax collapses it to one). W&B
    categoricals carry no order; declaring `is_ordered` explicitly also silences
    Ax's "is_ordered not specified" warning.
    """
    return ax.ChoiceParameterConfig(
        name=name,
        values=values,
        parameter_type=_value_type(values),
        is_ordered=False,
    )


def _infer_distribution_name(name: str, parameter: dict[str, Any]) -> str:
    """Return the sweep distribution W&B infers when the spec names none."""
    if "min" not in parameter or "max" not in parameter:
        raise ValueError(
            f"Cannot infer an Ax parameter from sweep parameter {name!r}: {parameter!r}"
        )
    lo, hi = parameter["min"], parameter["max"]
    return "int_uniform" if _is_int(lo) and _is_int(hi) else "uniform"


def _choice_config_for(name: str, parameter: dict[str, Any]) -> Any:
    """Build a choice config from a `values` list or a lone `value`."""
    if "values" in parameter:
        return _choice_config(name, list(parameter["values"]))
    return _choice_config(name, [parameter["value"]])


def sweep_parameter_to_parameter(name: str, parameter: dict[str, Any]) -> Any:
    """Convert a W&B sweep parameter spec into an Ax parameter config.

    Returns an `ax.RangeParameterConfig` / `ax.ChoiceParameterConfig` — the
    objects Ax's `Client.configure_experiment(parameters=[...])` accepts.
    Inverse of `parameter_to_sweep_parameter`. Distributions with no Ax
    equivalent (normal, beta, inv_log_uniform, ..., and `q_log_uniform_values`
    with `q != 1`, which would need a quantized log range) raise ValueError.
    """
    # Constant / categorical shorthands: `distribution` is optional in W&B.
    if "value" in parameter or (
        "values" in parameter and "distribution" not in parameter
    ):
        return _choice_config_for(name, parameter)

    # Without an explicit distribution, W&B infers one from min/max.
    dist = parameter.get("distribution") or _infer_distribution_name(name, parameter)

    if dist in ("categorical", "constant"):
        return _choice_config_for(name, parameter)

    if dist == "int_uniform":
        return ax.RangeParameterConfig(
            name=name,
            bounds=(int(parameter["min"]), int(parameter["max"])),
            parameter_type="int",
        )

    if dist == "uniform":
        return ax.RangeParameterConfig(
            name=name,
            bounds=(float(parameter["min"]), float(parameter["max"])),
            parameter_type="float",
        )

    if dist == "log_uniform_values":
        return ax.RangeParameterConfig(
            name=name,
            bounds=(float(parameter["min"]), float(parameter["max"])),
            parameter_type="float",
            scaling="log",
        )

    if dist == "q_uniform":
        lo, hi, q = parameter["min"], parameter["max"], parameter["q"]
        parameter_type: Literal["int", "float"] = (
            "int" if _is_int(lo) and _is_int(hi) and _is_int(q) else "float"
        )
        return ax.RangeParameterConfig(
            name=name,
            bounds=(float(lo), float(hi)),
            parameter_type=parameter_type,
            step_size=float(q),
        )

    if dist == "q_log_uniform_values":
        # parameter_to_sweep_parameter emits this (with q=1) for a log-scale int
        # range; Ax can't combine a log scale with a step, so only q=1
        # round-trips.
        q = parameter.get("q", 1)
        if not _is_int(q) or int(q) != 1:
            raise ValueError(
                f"Sweep parameter {name!r} uses q_log_uniform_values with q={q!r}; "
                "Ax cannot combine a log scale with a step, so only q=1 (a log-scale "
                "int range) is supported."
            )
        return ax.RangeParameterConfig(
            name=name,
            bounds=(int(parameter["min"]), int(parameter["max"])),
            parameter_type="int",
            scaling="log",
        )

    raise ValueError(
        f"Sweep distribution {dist!r} for parameter {name!r} has no Ax equivalent "
        "and cannot be converted."
    )


def sweep_config_to_search_space(config: dict[str, Any]) -> list[Any]:
    """Convert a sweep config's `parameters` block into an Ax search space."""
    return sweep_parameters_to_search_space(config.get("parameters", {}))


def sweep_parameters_to_search_space(
    parameters: dict[str, Any],
) -> list[Any]:
    """Convert a sweep config's `parameters` block into an Ax search space.

    Returns the list of `RangeParameterConfig` / `ChoiceParameterConfig` objects
    that Ax's `Client` accepts, e.g.:

        client.configure_experiment(
            parameters=sweep_parameters_to_search_space(config["parameters"]),
        )

    Inverse of `search_space_to_sweep_parameters`.
    """
    return [
        sweep_parameter_to_parameter(name, spec) for name, spec in parameters.items()
    ]


def sweep_config_to_objective(config: dict[str, Any]) -> str:
    """Return the Ax objective string for a sweep config's metric."""
    # TODO(kmikowicz): multi objective support
    return sweep_objective_to_objective(config.get("metric", {}))


def sweep_objective_to_objective(objective: dict[str, Any]) -> str:
    """Render a sweep metric as an Ax objective, negated to maximize.

    Raises:
        ValueError: If the metric has no name.
    """
    if "name" not in objective:
        raise ValueError(
            "Sweep config has no metric name; cannot build the Ax objective."
        )
    return f"{'' if objective.get('goal') == 'maximize' else '-'}{objective['name']}"


def _experiment(client: ax.Client) -> Any:
    """Return the `Client`'s configured experiment.

    The Ax `Client` keeps the experiment private and exposes no public accessor,
    so read the private attribute (trying both names Ax has used) and fail
    clearly if the client hasn't been configured yet.
    """
    for attr in ("_experiment", "_maybe_experiment"):
        experiment = getattr(client, attr, None)
        if experiment is not None:
            return experiment
    raise ValueError(
        "The Ax client has no configured experiment; call configure_experiment "
        "(and configure_optimization) first."
    )


def _single_objective(client: ax.Client) -> tuple[str, bool]:
    """Return `(metric_name, minimize)` for the client's single objective.

    Raises ValueError when the experiment has no objective or optimizes more
    than one metric — this scheduler drives a single sweep metric only.
    """
    optimization_config = _experiment(client).optimization_config
    if optimization_config is None:
        raise ValueError(
            "The Ax client has no optimization config; call configure_optimization "
            "first."
        )
    if getattr(optimization_config, "is_moo_problem", False):
        raise ValueError(
            "AxOptimizer only supports single-objective experiments; the Ax "
            "experiment defines multiple objectives."
        )
    metric_names = optimization_config.objective.metric_names
    if not metric_names or len(metric_names) != 1:
        raise ValueError(
            "AxOptimizer only supports a single scalar objective; the Ax "
            f"experiment's objective covers {list(metric_names)}."
        )
    return metric_names[0], bool(optimization_config.objective.minimize)


def sweep_from_experiment(
    client: ax.Client,
    entity: str,
    project: str,
    program_path: str | None = None,
) -> str:
    """Create a W&B sweep mirroring an Ax experiment's space and objective.

    The experiment's objective direction maps onto the sweep metric's goal
    (`minimize` / `maximize`) and its name onto the metric the runs log and the
    optimizer reads back. `program_path`, if given, sets the sweep's training
    program.

    Returns:
        The created sweep's id.
    """
    metric_name, minimize = _single_objective(client)
    config: dict[str, Any] = {
        "metric": {
            "name": metric_name,
            "goal": "minimize" if minimize else "maximize",
        },
        "parameters": search_space_to_sweep_parameters(
            _experiment(client).search_space
        ),
        "scheduler": {
            "engine": "ax",
        },
    }
    if program_path is not None:
        config["program"] = program_path

    return wandb_sweep(config, entity=entity, project=project)


class AxOptimizer(Optimizer):
    """`Optimizer` driven by an Ax experiment via its ask/tell `Client`.

    Ask/tell maps directly onto Ax: `get_next_trials` proposes parameterizations
    keyed by trial index (used as the optimizer run id), `complete_trial`
    records a finished run's objective, and `mark_trial_failed` records a failed
    one. Ax owns all search state, so this class holds none of its own.
    """

    @override
    def __init__(
        self,
        client: ax.Client,
        sweep: SweepInfo,
        terminator: TerminatorCallback | None = None,
    ):
        # Set before super().__init__, which calls validate_sweep_objective().
        self.client = client
        self._terminator = terminator
        # Ax raises when a trial is finalized twice, so remember which
        # trials this optimizer already completed, failed or stopped: the
        # scheduler may legitimately repeat a terminal tell or a prune.
        self._finalized: set[int] = set()
        super().__init__(sweep)

    @override
    def should_terminate_sweep(self) -> bool:
        """Return True once the caller's `terminator` says the search is done.

        `terminator` is supplied via `AxOptions`; the default is `None`,
        which never terminates early.
        """
        return self._terminator is not None and self._terminator(self.client)

    @override
    def validate_sweep_objective(self) -> None:
        """Fail fast if experiment and sweep disagree on the objective."""
        if self._sweep.config.get("metrics") is not None:
            # Ax's ask/tell client optimizes one scalar objective, so say so
            # rather than failing later on the sweep's missing `metric`.
            raise ValueError(
                "AxOptimizer only supports single-objective sweeps; this "
                "sweep declares multiple metrics. Use a sweep config with a "
                "single `metric` instead."
            )

        metric_name, minimize = _single_objective(self.client)
        goal = "minimize" if minimize else "maximize"

        sweep_metric = self._sweep.config.get("metric") or {}
        sweep_goal = str(sweep_metric.get("goal", "minimize")).lower()
        if goal != sweep_goal:
            raise ValueError(
                f"Ax objective direction {goal!r} does not match the sweep metric "
                f"goal {sweep_goal!r}; set the experiment objective to {sweep_goal!r}."
            )

        sweep_metric_name = self.metric_key()
        if metric_name != sweep_metric_name:
            raise ValueError(
                f"Ax objective metric {metric_name!r} does not match the sweep "
                f"metric name {sweep_metric_name!r}."
            )

    @override
    def ask_n_runs(self, n: int) -> Sequence[RunSuggestion] | None:
        """Ask Ax for up to `n` trials and return them as suggestions.

        Returns None when Ax declines to generate this round (its strategy
        needs results from in-flight trials, or a parallelism cap is hit);
        the scheduler asks again on a later poll. Returns an empty sequence
        when Ax reports the optimization complete, finishing the sweep.
        Any other Ax failure propagates.
        """
        from ax.exceptions.core import DataRequiredError, OptimizationComplete
        from ax.exceptions.generation_strategy import MaxParallelismReachedException

        try:
            trials = self.client.get_next_trials(max_trials=n)
        except (DataRequiredError, MaxParallelismReachedException):
            # Transient: Ax wants results from in-flight trials before
            # generating more. Decline rather than propose an empty batch,
            # which would end the sweep as exhausted.
            return None
        except OptimizationComplete:
            # The search is done: the space is exhausted, a stopping
            # strategy fired, or the generation strategy completed.
            return []
        return [
            RunSuggestion(
                config=RunConfig.from_values(dict(parameters)),
                run_id=str(trial_index),
            )
            for trial_index, parameters in trials.items()
        ]

    @override
    def tell_run(self, run_id: Any, data: RunWithMetrics) -> None:
        """Report a trial's progress, completing it once the run is terminal.

        A run whose trial was already finalized -- at prune time, or by an
        earlier terminal tell -- is a no-op, per the Optimizer contract.
        """
        # run_id is the Ax trial index (as a str) from ask_n_runs/attach_trial.
        # In-flight runs get their latest metric value attached as intermediate
        # data (via progression) so `prune_run`'s should_stop_trial_early has
        # something to judge; the trial itself is only finalized once terminal.
        trial_index = int(run_id)
        if trial_index in self._finalized:
            return
        if data.state.is_alive:
            # RUNNING/PENDING/PREEMPTING/UNKNOWN: still producing results.
            self._attach_latest_progression(trial_index, data)
            return
        self._finalized.add(trial_index)
        if data.state == RunState.FINISHED:
            value = self.metric_value(data.summary_metrics)
            if value is None:
                # Finished but never logged the objective metric — record a
                # failure so Ax stops tracking it as in flight.
                self.client.mark_trial_failed(trial_index=trial_index)
                return
            self.client.complete_trial(
                trial_index=trial_index, raw_data={self.metric_key(): value}
            )
        else:  # FAILED / CRASHED / KILLED / PREEMPTED
            self.client.mark_trial_failed(trial_index=trial_index)

    @override
    def forget_run(self, run_id: Any) -> None:
        """Fail the trial of a proposed run that will never start.

        Failing (rather than leaving it running) frees the trial's slot in
        Ax's parallelism accounting.
        """
        trial_index = int(run_id)
        if trial_index in self._finalized:
            return
        self._finalized.add(trial_index)
        self.client.mark_trial_failed(trial_index=trial_index)

    def _attach_latest_progression(
        self, trial_index: int, data: RunWithMetrics
    ) -> None:
        if not data.history_metrics:
            return
        row = data.history_metrics[-1]
        value = self.metric_value(row)
        if value is None:
            return
        try:
            self.client.attach_data(
                trial_index=trial_index,
                raw_data={self.metric_key(): value},
                progression=row["_step"],
            )
        except Exception:
            # Ax rejects a non-increasing progression (e.g. no new history since
            # the last poll); should_stop_trial_early just judges on what's
            # already attached.
            pass

    @override
    def prune_run(self, run_id: Any, data: RunWithMetrics) -> bool:
        """Return True if Ax's early-stopping strategy says to stop the run.

        A run whose trial was already finalized is never pruned again.
        """
        # On the first call Ax lazily configures a default (Percentile) early
        # stopping strategy if none was set explicitly, then judges this trial's
        # attached progressions against its peers at the same step.
        trial_index = int(run_id)
        if trial_index in self._finalized:
            return False
        try:
            if not self.client.should_stop_trial_early(trial_index=trial_index):
                return False
        except Exception:
            return False
        self._finalized.add(trial_index)
        self.client.mark_trial_early_stopped(trial_index=trial_index)
        return True

    @override
    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        """Warm-start the experiment by attaching an existing run as a trial.

        The run's config is attached as a manually-chosen arm and then finalized
        via `tell_run`. Runs whose config doesn't cover the experiment's search
        space, or finished runs that never logged the objective, are skipped.
        """
        if not is_terminal_state(data.state):
            return
        if (
            data.state == RunState.FINISHED
            and self.metric_value(data.summary_metrics) is None
        ):
            return
        params = self._search_space_params(data.config.flat_dict())
        if params is None:
            return
        trial_index = self.client.attach_trial(parameters=params)
        self.tell_run(trial_index, data)

    @override
    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an in-flight run by attaching its config as an Ax trial.

        The trial is left running — not completed — so the loop finalizes it via
        `tell_run` when the run reaches a terminal state. Returns the Ax trial
        index to track the run by, or None if the run's config doesn't cover the
        search space.
        """
        params = self._search_space_params(data.config.flat_dict())
        if params is None:
            return None
        return self.client.attach_trial(parameters=params)

    def _search_space_params(self, config: dict[str, Any]) -> dict[str, Any] | None:
        """Project a run's config onto the experiment's parameters.

        Returns just the search-space parameters (Ax rejects unknown keys), or
        None when the config is missing any of them (Ax requires a complete
        arm). Values are cast to each parameter's declared Ax type
        (`python_type`): a run's config round-trips through JSON, which
        collapses an integral float (e.g. `5.0`) down to an int (`5`), and Ax's
        own arm validation rejects a value whose Python type doesn't match the
        parameter's declared type.
        """
        parameters = _experiment(self.client).search_space.parameters
        if not all(name in config for name in parameters):
            return None
        return {
            name: parameter.python_type(config[name])
            for name, parameter in parameters.items()
        }


# ---------------------------------------------------------------------------
# Public entry points.  These free functions are the supported way to run a
# scheduler; callers should not instantiate `AxOptimizer` directly. Each
# drives the sweep until its scheduler stops: wandb-core owns the scheduling
# loop and this process hosts the optimizer.
# ---------------------------------------------------------------------------


def create_default_client(config: dict[str, Any]) -> ax.Client:
    """Build an Ax `Client` configured from a sweep config alone."""
    from ax.api.client import Client

    client = Client()
    client.configure_experiment(parameters=sweep_config_to_search_space(config))
    client.configure_optimization(objective=sweep_config_to_objective(config))
    return client


def _parse_sweep_path(sweep: str) -> tuple[str, str, str]:
    """Split an "entity/project/sweep_id" path into its parts."""
    parts = sweep.split("/") if sweep else []
    if len(parts) != 3 or not all(parts):
        raise ValueError(
            f"Expected a sweep path of the form entity/project/sweep_id, got: {sweep!r}"
        )
    entity, project, sweep_id = parts
    return entity, project, sweep_id


def resume_sweep(
    sweep: str,
    *,
    options: AxOptions | None = None,
) -> None:
    """Run a scheduler on a sweep that already exists, until it stops.

    `sweep` is an "entity/project/sweep_id" path string. `options.client`
    is required: the Ax experiment it owns supplies the search space and
    objective, which the sweep is validated to agree with. The sweep's
    prior runs warm-start the experiment.

    Raises:
        ValueError: If `options.client` is missing or `sweep` is not a full
            sweep path.
    """
    entity, project, sweep_id = _parse_sweep_path(sweep)
    options = options or AxOptions()
    client = options.client
    if client is None:
        raise ValueError("`options.client` is required")
    run_scheduler(
        entity=entity,
        project=project,
        sweep_id=sweep_id,
        make_optimizer=lambda info: AxOptimizer(client, info, options.terminator),
        batch_size=options.batch_size,
        poll_interval=options.poll_interval_s,
    )


def create_sweep(
    entity: str,
    project: str,
    *,
    program_path: str | None = None,
    options: AxOptions | None = None,
) -> str:
    """Create a sweep from the Ax experiment's space, then run its scheduler.

    `options.client` is required. The metric name and goal are taken from the
    experiment's objective, so -- unlike the optuna entry point -- no
    `metric_name` is needed.

    Args:
        entity: The entity to create the sweep under.
        project: The project to create the sweep under.
        program_path: The training program recorded in the sweep config.
        options: `options.client` is required; its configured experiment
            supplies the parameter space and objective.

    Returns:
        The sweep's id.

    Raises:
        ValueError: If `options.client` is missing or `entity` or `project`
            is empty.
    """
    if not entity or not project:
        raise ValueError("entity and project must be non-empty")
    options = options or AxOptions()
    if options.client is None:
        raise ValueError("`options.client` is required")
    sweep_id = sweep_from_experiment(options.client, entity, project, program_path)
    resume_sweep(f"{entity}/{project}/{sweep_id}", options=options)
    return sweep_id


def create_sweep_from_config(
    config: dict[str, Any],
    entity: str,
    project: str,
    *,
    options: AxOptions | None = None,
) -> str:
    """Create the client and the sweep, then run its scheduler.

    When `options.client` is `None`, a client is built from the config via
    `create_default_client`, deriving the parameter space and objective from
    `config["parameters"]` and `config["metric"]`; a supplied client is used
    as-is, with the experiment it already owns.

    Args:
        config: The sweep config to create the sweep (and default client)
            from.
        entity: The entity to create the sweep under.
        project: The project to create the sweep under.
        options: Optional client/terminator overrides.

    Returns:
        The sweep's id.

    Raises:
        ValueError: If `entity` or `project` is empty.
    """
    if not entity or not project:
        raise ValueError("entity and project must be non-empty")

    engine = (config.get("scheduler") or {}).get("engine", "ax")
    if engine != "ax":
        raise ValueError(
            f"config selects the {engine!r} engine; use that engine's "
            f"create_sweep_from_config instead."
        )
    # The server only lets this scheduler enqueue runs for a sweep whose
    # config says the search runs locally.
    config = {**config, "scheduler": {"engine": "ax"}}

    options = options or AxOptions()
    client = options.client
    if client is None:
        client = create_default_client(config)
    resolved_client = client
    sweep_id = wandb_sweep(config, entity=entity, project=project)
    run_scheduler(
        entity=entity,
        project=project,
        sweep_id=sweep_id,
        make_optimizer=lambda info: AxOptimizer(
            resolved_client, info, options.terminator
        ),
        batch_size=options.batch_size,
        poll_interval=options.poll_interval_s,
    )
    return sweep_id
