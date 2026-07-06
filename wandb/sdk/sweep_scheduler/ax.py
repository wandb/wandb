"""Sweep scheduler backed by an Ax experiment (Adaptive Experimentation Platform).

Mirrors ``optuna.py`` but drives the search with Ax's ask/tell ``Client``
(``ax.Client``), which owns the experiment — its search space, objective and
generation strategy. Free functions build or attach a W&B sweep and return a
``Scheduler`` whose ``.loop()`` drives it:

  - `create_sweep`  derives a new W&B sweep from the client's experiment
                    (search space + objective) and attaches a scheduler.
  - `resume_sweep`  attaches a scheduler to a sweep that already exists.

Unlike optuna there is no define-by-run flavor: Ax's search space is declared up
front on the experiment, so there is a single `AxOptimizer`. The optimizer maps
the ask/tell loop onto the Client: `get_next_trials` proposes runs,
`complete_trial` records finished ones (and `mark_trial_failed` failed ones), and
`attach_trial` adopts runs that predate the scheduler at warm-start.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from wandb import Api, util
from wandb import sweep as wandb_sweep
from wandb.apis.public import Sweep
from wandb.sdk.launch.sweeps.scheduler import RunState
from wandb.sdk.sweep_scheduler.optimizer import (
    Optimizer,
    Run,
    RunEnriched,
    RunSuggestion,
    terminal_state,
)
from wandb.sdk.sweep_scheduler.scheduler import (
    Executor,
    InMemoryScheduler,
    Scheduler,
    scheduler_sweep_config,
)

ax = util.get_module(
    "ax",
    required="wandb[ax] is required to use the Ax sweep scheduler. "
    "Please run `pip install wandb[ax]`.",
)


def parameter_to_sweep_parameter(parameter: Any) -> dict[str, Any]:
    """Convert a single Ax (core) parameter into a W&B sweep config parameter spec.

    ``parameter`` is one of the experiment's live parameters (e.g. an
    ``ax.core.parameter.RangeParameter``), as read from
    ``client._experiment.search_space.parameters``. The returned dict is the value
    for one entry under a sweep config's ``parameters`` block (e.g.
    ``{"distribution": "uniform", "min": 0, "max": 1}``).
    """
    # Ax's core parameter classes aren't exported at the top level, so import them
    # here (ax is guaranteed installed once this module imports).
    from ax.core.parameter import ChoiceParameter, FixedParameter, RangeParameter

    if isinstance(parameter, RangeParameter):
        low, high = parameter.lower, parameter.upper
        if parameter.parameter_type.name == "INT":
            if parameter.log_scale:
                # W&B has no native int-log; sample log-uniform in value space and
                # round to integers (q=1), matching the optuna scheduler.
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
    """Convert an Ax search space into a sweep config ``parameters`` block."""
    return {
        name: parameter_to_sweep_parameter(parameter)
        for name, parameter in search_space.parameters.items()
    }


def _is_int(value: Any) -> bool:
    # bool is a subclass of int but is never a numeric bound/choice here.
    return isinstance(value, int) and not isinstance(value, bool)


def _value_type(values: list[Any]) -> str:
    """Infer the Ax ``parameter_type`` for a set of categorical / constant values.

    Returns one of ``"bool"`` / ``"int"`` / ``"float"`` / ``"str"`` — the strings
    Ax's ``ChoiceParameterConfig`` expects.
    """
    if values and all(isinstance(v, bool) for v in values):
        return "bool"
    if values and all(_is_int(v) for v in values):
        return "int"
    if values and all(isinstance(v, (int, float)) for v in values):
        return "float"
    return "str"


def _choice_config(name: str, values: list[Any]) -> Any:
    """Build an Ax ``ChoiceParameterConfig`` from W&B ``values``.

    A single-value list becomes a fixed parameter (Ax collapses it to one). W&B
    categoricals carry no order; declaring ``is_ordered`` explicitly also silences
    Ax's "is_ordered not specified" warning.
    """
    return ax.ChoiceParameterConfig(
        name=name,
        values=values,
        parameter_type=_value_type(values),
        is_ordered=False,
    )


def sweep_parameter_to_parameter(name: str, parameter: dict[str, Any]) -> Any:
    """Convert a single W&B sweep config parameter spec into an Ax parameter config.

    Returns an ``ax.RangeParameterConfig`` / ``ax.ChoiceParameterConfig`` — the
    objects Ax's ``Client.configure_experiment(parameters=[...])`` accepts. Inverse
    of `parameter_to_sweep_parameter`. Distributions with no Ax equivalent (normal,
    beta, inv_log_uniform, ..., and `q_log_uniform_values` with ``q != 1``, which
    would need a quantized log range) raise ValueError.
    """
    # Constant / categorical shorthands — the `distribution` key is optional in W&B.
    if "value" in parameter:
        return _choice_config(name, [parameter["value"]])
    if "values" in parameter and "distribution" not in parameter:
        return _choice_config(name, list(parameter["values"]))

    dist = parameter.get("distribution")
    if dist is None:
        # No explicit distribution: W&B infers int_uniform vs uniform from min/max.
        if "min" in parameter and "max" in parameter:
            lo, hi = parameter["min"], parameter["max"]
            dist = "int_uniform" if _is_int(lo) and _is_int(hi) else "uniform"
        else:
            raise ValueError(
                f"Cannot infer an Ax parameter from sweep parameter {name!r}: "
                f"{parameter!r}"
            )

    if dist in ("categorical", "constant"):
        if "values" in parameter:
            return _choice_config(name, list(parameter["values"]))
        return _choice_config(name, [parameter["value"]])

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
        if _is_int(lo) and _is_int(hi) and _is_int(q):
            bounds, parameter_type = (int(lo), int(hi)), "int"
        else:
            bounds, parameter_type = (float(lo), float(hi)), "float"
        return ax.RangeParameterConfig(
            name=name, bounds=bounds, parameter_type=parameter_type, step_size=q
        )

    if dist == "q_log_uniform_values":
        # parameter_to_sweep_parameter emits this (with q=1) for a log-scale int
        # range; Ax can't combine a log scale with a step, so only q=1 round-trips.
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
    return sweep_parameters_to_search_space(config.get("parameters", {}))

def sweep_parameters_to_search_space(
    parameters: dict[str, Any],
) -> list[Any]:
    """Convert a sweep config's ``parameters`` block into an Ax search space.

    Returns the list of ``RangeParameterConfig`` / ``ChoiceParameterConfig`` objects
    that Ax's ``Client`` accepts, e.g.::

        client.configure_experiment(
            parameters=sweep_parameters_to_search_space(config["parameters"]),
        )

    Inverse of `search_space_to_sweep_parameters`.
    """
    return [
        sweep_parameter_to_parameter(name, spec) for name, spec in parameters.items()
    ]

def sweep_config_to_objective(config: dict[str, Any]) -> str:
    # TODO(kmikowicz): multi objective support
    return sweep_objective_to_objective(config.get("metric", {}))

def sweep_objective_to_objective(objective: dict[str, Any]) -> str:
    return f"{'' if objective['goal'] == 'maximize' else '-' }{objective['name']}"

def _experiment(client: ax.Client) -> Any:
    """Return the ``Client``'s configured experiment.

    The Ax ``Client`` keeps the experiment private and exposes no public accessor,
    so read the private attribute (trying both names Ax has used) and fail clearly
    if the client hasn't been configured yet.
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
    """Return ``(metric_name, minimize)`` for the client's single objective.

    Raises ValueError when the experiment has no objective or optimizes more than
    one metric — this scheduler drives a single sweep metric only.
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
) -> Sweep:
    """Create a W&B sweep mirroring an Ax experiment's search space and objective.

    The experiment's objective direction maps onto the sweep metric's goal
    (``minimize`` / ``maximize``) and its name onto the metric the runs log and the
    optimizer reads back. ``program_path``, if given, sets the sweep's training
    program.
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
        **scheduler_sweep_config,
    }
    if program_path is not None:
        config["program"] = program_path

    sid = wandb_sweep(config, entity=entity, project=project)
    return Api().sweep(f"{entity}/{project}/{sid}")


class AxOptimizer(Optimizer):
    """`Optimizer` driven by an Ax experiment via its ask/tell `Client`.

    Ask/tell maps directly onto Ax: `get_next_trials` proposes parameterizations
    keyed by trial index (used as the optimizer run id), `complete_trial` records a
    finished run's objective, and `mark_trial_failed` records a failed one. Ax owns
    all search state, so this class holds none of its own.
    """

    def __init__(self, client: ax.Client, sweep: Sweep):
        # Set before super().__init__, which calls validate_sweep_objective().
        self.client = client
        super().__init__(sweep)

    def validate_sweep_objective(self) -> None:
        """Fail fast if the Ax experiment and the sweep disagree on the objective."""
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

    def next_n_runs(self, n: int) -> Iterable[RunSuggestion]:
        try:
            trials = self.client.get_next_trials(max_trials=n)
        except Exception:
            # Ax may decline to generate more until in-flight trials complete (e.g.
            # its generation strategy needs data, or a parallelism cap is hit).
            # Propose nothing this round; the scheduler retries next poll as runs
            # finish. run_id is the Ax trial index so tell_run can address the trial.
            return []
        return [
            RunSuggestion(config=dict(parameters), run_id=trial_index)
            for trial_index, parameters in trials.items()
        ]

    def tell_run(self, run_id: Any, data: RunEnriched) -> None:
        # run_id is the Ax trial index from next_n_runs / attach_trial. Ax's ask-tell
        # has no intermediate reporting, so only terminal runs are told; the loop
        # keeps polling in-flight ones until they reach a terminal state.
        if data.state in (RunState.RUNNING, RunState.PENDING):
            return
        if data.state == RunState.FINISHED:
            value = self.metric_value(data.summary_metrics)
            if value is None:
                # Finished but never logged the objective metric — record a failure
                # so Ax stops tracking it as in flight.
                self.client.mark_trial_failed(trial_index=run_id)
                return
            self.client.complete_trial(
                trial_index=run_id, raw_data={self.metric_key(): value}
            )
        else:  # FAILED / CRASHED / KILLED
            self.client.mark_trial_failed(trial_index=run_id)

    def tell_existing_finished_run(self, data: RunEnriched) -> None:
        """Warm-start the experiment by attaching an existing run as a trial.

        The run's config is attached as a manually-chosen arm and then finalized via
        `tell_run`. Runs whose config doesn't cover the experiment's search space,
        or finished runs that never logged the objective, are skipped.
        """
        run_state = terminal_state(data.state)
        if run_state is None:
            return
        if (
            run_state == RunState.FINISHED
            and self.metric_value(data.summary_metrics) is None
        ):
            return
        params = self._search_space_params(data.config)
        if params is None:
            return
        trial_index = self.client.attach_trial(parameters=params)
        self.tell_run(trial_index, data)

    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an in-flight run by attaching its config as an Ax trial.

        The trial is left running — not completed — so the loop finalizes it via
        `tell_run` when the run reaches a terminal state. Returns the Ax trial index
        to track the run by, or None if the run's config doesn't cover the search
        space.
        """
        params = self._search_space_params(data.config)
        if params is None:
            return None
        return self.client.attach_trial(parameters=params)

    def _search_space_params(self, config: dict[str, Any]) -> dict[str, Any] | None:
        """Project a run's config onto the experiment's parameters.

        Returns just the search-space parameters (Ax rejects unknown keys), or None
        when the config is missing any of them (Ax requires a complete arm). Values
        are cast to each parameter's declared Ax type (``python_type``): a run's
        config round-trips through JSON, which collapses an integral float (e.g.
        ``5.0``) down to an int (``5``), and Ax's own arm validation rejects a value
        whose Python type doesn't match the parameter's declared type.
        """
        parameters = _experiment(self.client).search_space.parameters
        if not all(name in config for name in parameters):
            return None
        return {
            name: parameter.python_type(config[name])
            for name, parameter in parameters.items()
        }


# ---------------------------------------------------------------------------
# Public entry points.
#
# These free functions are the supported way to build a scheduler; callers should
# not instantiate `AxOptimizer` directly. Each returns a Scheduler whose `.loop()`
# drives the sweep.
# ---------------------------------------------------------------------------

def create_default_client(config: dict[str, Any]) -> ax.Client:
    from ax.api.client import Client

    client = Client()
    client.configure_experiment(parameters=sweep_config_to_search_space(config))
    client.configure_optimization(objective=sweep_config_to_objective(config))
    return client

def resume_sweep(
    client: ax.Client,
    sweep: Sweep | str,
    *,
    poll_interval_s: float = 5.0,
    batch_size: int = 1,
    executor: Callable[[Sweep], Executor] | None = None,
) -> Scheduler:
    """Attach a scheduler to a sweep that already exists.

    `sweep` may be a `Sweep` or an "entity/project/sweep_id" path string. The Ax
    experiment (via `client`) supplies the search space and objective; the sweep is
    validated to agree with it. `executor` is a factory taking the resolved sweep
    and returning the backend that schedules runs (defaults to the W&B run queue).
    """
    if isinstance(sweep, str):
        sweep = Api().sweep(sweep)
    optimizer = AxOptimizer(client, sweep)
    return InMemoryScheduler(
        optimizer,
        sweep,
        poll_interval_s,
        batch_size,
        executor(sweep) if executor is not None else None,
    )


def create_sweep(
    client: ax.Client,
    entity: str,
    project: str,
    *,
    poll_interval_s: float = 5.0,
    batch_size: int = 1,
    program_path: str | None = None,
    executor: Callable[[Sweep], Executor] | None = None,
) -> Scheduler:
    """Create a new sweep from the Ax experiment's search space, then attach a scheduler.

    The metric name and goal are taken from the experiment's objective, so — unlike
    the optuna entry point — no `metric_name` is needed. `executor` is a factory
    taking the created sweep and returning the backend that schedules runs (defaults
    to the W&B run queue).
    """
    sweep = sweep_from_experiment(client, entity, project, program_path)
    optimizer = AxOptimizer(client, sweep)
    return InMemoryScheduler(
        optimizer,
        sweep,
        poll_interval_s,
        batch_size,
        executor(sweep) if executor is not None else None,
    )
