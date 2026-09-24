from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

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

# Trial run metadata linking an experiment's trials to the sweep, so a client
# the caller persisted and reloaded is resumed on warm start, not refilled.
_SWEEP_KEY = "wandb_sweep"
_WANDB_RUN_ID_KEY = "wandb_run_id"

# A claimed persisted trial that already finished, so its run has nothing
# left to tell.
_FINISHED = object()


@dataclass
class _PersistedIndex:
    """Trial indices of the trials a reloaded client holds for the sweep."""

    # W&B run id to the index of its still-running trial.
    running_by_run: dict[str, int] = field(default_factory=dict)
    # W&B run ids whose trial already finished.
    finished_runs: set[str] = field(default_factory=set)
    # Indices of the sweep's running trials no run was seen for yet.
    unlinked_running: list[int] = field(default_factory=list)


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
    Distributions with no Ax equivalent (normal, beta, inv_log_uniform, ...,
    and `q_log_uniform_values` with `q != 1`, which would need a quantized
    log range) raise ValueError.
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
        lo, hi, q = parameter["min"], parameter["max"], parameter.get("q", 1)
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
        # W&B spells a log-scale int range this way (with q=1); Ax can't
        # combine a log scale with a step, so only q=1 round-trips.
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
    """
    return [
        sweep_parameter_to_parameter(name, spec) for name, spec in parameters.items()
    ]


def sweep_config_to_metrics(config: dict[str, Any]) -> list[Any]:
    """Return the Ax metrics to optimize for a sweep config's objectives.

    A multi-objective sweep declares its objectives in `metrics`, a
    single-objective one in `metric`.
    """
    metrics = config.get("metrics")
    if metrics is not None:
        return [sweep_objective_to_metric(objective) for objective in metrics]
    return [sweep_objective_to_metric(config.get("metric", {}))]


def sweep_objective_to_metric(objective: dict[str, Any]) -> Any:
    """Convert a sweep metric into the Ax metric to optimize.

    Returns an `ax.core.map_metric.MapMetric` — rather than a plain `Metric`,
    so Ax accepts the per-step data `AxOptimizer` attaches for early stopping —
    whose `lower_is_better` carries the sweep's goal.

    Raises:
        ValueError: If the metric has no name.
    """
    from ax.core.map_metric import MapMetric

    if "name" not in objective:
        raise ValueError(
            "Sweep config has no metric name; cannot build the Ax objective."
        )
    return MapMetric(
        name=objective["name"],
        lower_is_better=objective.get("goal") != "maximize",
    )


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


def _experiment_objectives(client: ax.Client) -> list[tuple[str, bool]]:
    """Return `(metric_name, minimize)` for each objective the client optimizes.

    Raises ValueError when the experiment has no objective, or optimizes a
    scalarized one — a weighted sum of metrics has no per-metric goal to check
    a sweep's `metrics` against.
    """
    optimization_config = _experiment(client).optimization_config
    if optimization_config is None:
        raise ValueError(
            "The Ax client has no optimization config; call configure_optimization "
            "first."
        )
    objective = optimization_config.objective
    if getattr(objective, "is_scalarized_objective", False):
        raise ValueError(
            "AxOptimizer does not support a scalarized Ax objective; declare one "
            "objective per sweep metric instead."
        )
    # Ax encodes a minimized objective as a negative metric weight, for both
    # single- and multi-objective configs.
    weights = list(objective.metric_weights)
    if not weights:
        raise ValueError("The Ax experiment's objective covers no metric.")
    return [(name, weight < 0) for name, weight in weights]


class AxOptimizer(Optimizer):
    """`Optimizer` driven by an Ax experiment via its ask/tell `Client`.

    Ask/tell maps directly onto Ax: `get_next_trials` proposes parameterizations
    keyed by trial index (used as the optimizer run id), `complete_trial`
    records a finished run's objective, and `mark_trial_failed` records a failed
    one. Ax owns all search state, so this class holds none of its own.

    A client reloaded from the caller's own storage (e.g.
    `Client.load_from_json_file`) may already hold this sweep's trials: each
    trial records its W&B run id under the `wandb_run_id` key of its run
    metadata. Warm start resumes those trials rather than attaching the
    sweep's runs again, and adopts in-flight runs onto their still-running
    trials.
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
        # Trials already stamped with their W&B run id.
        self._linked: set[int] = set()
        super().__init__(sweep)

        self._sweep_path = f"{sweep.entity}/{sweep.project}/{sweep.id}"
        # Built on the first warm-start call and dropped once generation
        # starts; see `_index_persisted_trials`.
        self._warm_start_over = False
        self._persisted_index: _PersistedIndex | None = None

    def _persisted_trials(self) -> Iterator[Any]:
        """Yield the experiment's trials one at a time, uncopied."""
        # The client holds its whole experiment in memory; the trials are
        # handed over from it as they are.
        yield from _experiment(self.client).trials.values()

    def _index_persisted_trials(self) -> _PersistedIndex:
        """Index the trials a caller's client already holds for this sweep.

        Only trial indices are kept, never the trials: linked trials by W&B
        run id, and running trials this sweep asked for but never saw
        polled, which carry no run id yet and are matched to their run by
        params.
        """
        from ax.core.base_trial import TrialStatus

        if self._persisted_index is not None:
            return self._persisted_index
        index = _PersistedIndex()
        for trial in self._persisted_trials():
            wandb_run_id = trial.run_metadata.get(_WANDB_RUN_ID_KEY)
            running = trial.status == TrialStatus.RUNNING
            if wandb_run_id is not None:
                if running:
                    index.running_by_run[wandb_run_id] = trial.index
                else:
                    index.finished_runs.add(wandb_run_id)
            elif running and trial.run_metadata.get(_SWEEP_KEY) == self._sweep_path:
                index.unlinked_running.append(trial.index)
        self._persisted_index = index
        return index

    def _claim_persisted_trial(self, data: Run) -> Any:
        """Take the client's existing trial for a warm-start run.

        Returns:
            The index of the run's still-running trial, `_FINISHED` if its
            trial already finished, or None if the client has none.
        """
        if self._warm_start_over:
            return None
        index = self._index_persisted_trials()
        if data.wandb_run_id in index.finished_runs:
            index.finished_runs.discard(data.wandb_run_id)
            return _FINISHED
        trial_index = index.running_by_run.pop(data.wandb_run_id, None)
        if trial_index is not None or not index.unlinked_running:
            return trial_index
        params = self._search_space_params(data.config.flat_dict())
        if params is None:
            return None
        trials = _experiment(self.client).trials
        for i, candidate in enumerate(index.unlinked_running):
            arm = getattr(trials[candidate], "arm", None)
            if arm is not None and arm.parameters == params:
                return index.unlinked_running.pop(i)
        return None

    def _end_warm_start(self) -> None:
        """Drop the warm-start index; later runs are the scheduler's own."""
        self._warm_start_over = True
        self._persisted_index = None

    def _stamp(self, trial_index: int, metadata: dict[str, Any]) -> None:
        """Merge sweep bookkeeping into a trial's run metadata."""
        _experiment(self.client).trials[trial_index].update_run_metadata(metadata)

    def _link(self, trial_index: int, wandb_run_id: str) -> None:
        """Record a trial's W&B run id in its run metadata, once."""
        if trial_index in self._linked or not wandb_run_id:
            return
        self._stamp(trial_index, {_WANDB_RUN_ID_KEY: wandb_run_id})
        self._linked.add(trial_index)

    def _finalize(self, trial_index: int) -> None:
        """Record that a trial got its outcome and is no longer tracked."""
        self._finalized.add(trial_index)
        self._linked.discard(trial_index)

    def _attach(self, params: dict[str, Any]) -> int:
        """Attach a run's params as a new trial owned by this sweep."""
        trial_index = self.client.attach_trial(parameters=params)
        self._stamp(trial_index, {_SWEEP_KEY: self._sweep_path})
        return trial_index

    @override
    def should_terminate_sweep(self) -> bool:
        """Return True once the caller's `terminator` says the search is done.

        `terminator` comes from the sweep's `scheduler.optimizer` function;
        the default is `None`, which never terminates early.
        """
        return self._terminator is not None and self._terminator(self.client)

    @override
    def validate_sweep_objective(self) -> None:
        """Fail fast if experiment and sweep disagree on the objectives."""
        objectives = _experiment_objectives(self.client)
        sweep_names = self.metric_names()
        sweep_goals = self.metric_goals()
        if len(objectives) != len(sweep_names):
            raise ValueError(
                "The Ax experiment and the sweep config disagree on the "
                f"objectives: Ax optimizes {len(objectives)}, the sweep declares "
                f"{len(sweep_names)}."
            )

        for (metric_name, minimize), sweep_name, sweep_goal in zip(
            objectives, sweep_names, sweep_goals, strict=True
        ):
            goal = "minimize" if minimize else "maximize"
            if goal != sweep_goal:
                raise ValueError(
                    f"Ax objective direction {goal!r} for {metric_name!r} does not "
                    f"match the sweep metric goal {sweep_goal!r}; set the experiment "
                    f"objective to {sweep_goal!r}."
                )
            if metric_name != sweep_name:
                raise ValueError(
                    f"Ax objective metric {metric_name!r} does not match the sweep "
                    f"metric name {sweep_name!r}."
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

        # Warm start is over once the scheduler asks for new runs.
        self._end_warm_start()
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
        for trial_index in trials:
            self._stamp(trial_index, {_SWEEP_KEY: self._sweep_path})
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
        self._link(trial_index, data.wandb_run_id)
        if data.state.is_alive:
            # RUNNING/PENDING/PREEMPTING/UNKNOWN: still producing results.
            self._attach_latest_progression(trial_index, data)
            return
        if data.state == RunState.FINISHED:
            values = self.objective_values(data.summary_metrics)
            if values is None:
                # Finished but never logged every objective metric — record a
                # failure so Ax stops tracking it as in flight.
                self.client.mark_trial_failed(trial_index=trial_index)
                self._finalize(trial_index)
                return
            self.client.complete_trial(
                trial_index=trial_index, raw_data=self._raw_data(values)
            )
        else:  # FAILED / CRASHED / KILLED / PREEMPTED
            self.client.mark_trial_failed(trial_index=trial_index)
        self._finalize(trial_index)

    @override
    def forget_run(self, run_id: Any) -> None:
        """Fail the trial of a proposed run that will never start.

        Failing (rather than leaving it running) frees the trial's slot in
        Ax's parallelism accounting.
        """
        trial_index = int(run_id)
        if trial_index in self._finalized:
            return
        self._finalize(trial_index)
        self.client.mark_trial_failed(trial_index=trial_index)

    def _attach_latest_progression(
        self, trial_index: int, data: RunWithMetrics
    ) -> None:
        if not data.history_metrics:
            return
        row = data.history_metrics[-1]
        values = self.objective_values(row)
        if values is None:
            return
        try:
            self.client.attach_data(
                trial_index=trial_index,
                raw_data=self._raw_data(values),
                progression=row["_step"],
            )
        except Exception:
            # Ax rejects a non-increasing progression (e.g. no new history since
            # the last poll); should_stop_trial_early just judges on what's
            # already attached.
            pass

    def _raw_data(self, values: Sequence[Any]) -> dict[str, Any]:
        """Pair the sweep's objective values with the names Ax knows them by."""
        return dict(zip(self.metric_names(), values, strict=True))

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
        self._finalize(trial_index)
        self.client.mark_trial_early_stopped(trial_index=trial_index)
        return True

    @override
    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        """Warm-start the experiment by attaching an existing run as a trial.

        A client the caller persisted may already hold the run's trial. A
        finished one is left as is; a running one -- the run ended while no
        scheduler watched it -- is finalized with the run's result.

        Otherwise the run's config is attached as a manually-chosen arm and
        then finalized via `tell_run`. Runs whose config doesn't cover the
        experiment's search space, or finished runs that never logged the
        objective, are skipped.
        """
        if not is_terminal_state(data.state):
            return
        claimed = self._claim_persisted_trial(data)
        if claimed is not None:
            if claimed is not _FINISHED:
                self.tell_run(claimed, data)
            return
        if (
            data.state == RunState.FINISHED
            and self.objective_values(data.summary_metrics) is None
        ):
            return
        params = self._search_space_params(data.config.flat_dict())
        if params is None:
            return
        self.tell_run(self._attach(params), data)

    @override
    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an in-flight run, resuming its trial if the client has one.

        A client the caller persisted may already hold the run's trial. A
        running one is tracked again under its own index; a finished one
        already records the run's outcome, so the run is left untracked
        rather than duplicated.

        Otherwise the run's config is attached as a new trial. The trial is
        left running — not completed — so the loop finalizes it via `tell_run`
        when the run reaches a terminal state.

        Returns:
            The Ax trial index to track the run by, or None if the client
            already finished the run's trial or the run's config doesn't
            cover the search space.
        """
        claimed = self._claim_persisted_trial(data)
        if claimed is _FINISHED:
            return None
        if claimed is not None:
            self._link(claimed, data.wandb_run_id)
            return claimed
        params = self._search_space_params(data.config.flat_dict())
        if params is None:
            return None
        trial_index = self._attach(params)
        self._link(trial_index, data.wandb_run_id)
        return trial_index

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
# Optimizer construction.
#
# A sweep whose `scheduler.optimizer` names no Ax client of its own is
# driven by the client this builds from the sweep's config.
# ---------------------------------------------------------------------------


def configure_sweep_objective(client: ax.Client, config: dict[str, Any]) -> None:
    """Set a client's optimization config from a sweep config's metric(s).

    Use this rather than Ax's `Client.configure_optimization`, which takes an
    objective expression that Ax parses with sympy: it only escapes `.`, `/`,
    `:` and `~`, so a metric named `val-loss` becomes the two metrics `val`
    and `loss`, and a name with a space, a `%` or a leading digit is rejected.
    Naming the metric keeps whatever the sweep called it.

    Args:
        client: An Ax client whose experiment is already configured.
        config: A sweep config, whose `metric` or `metrics` block names the
            objective(s).
    """
    from ax.core.objective import MultiObjective, Objective
    from ax.core.optimization_config import (
        MultiObjectiveOptimizationConfig,
        OptimizationConfig,
    )

    metrics = sweep_config_to_metrics(config)
    experiment = _experiment(client)
    for metric in metrics:
        # Ax validates an optimization config against the experiment's metrics.
        experiment.add_metric(metric)
    # Ax deprecated `metric` for `expression`, but only it skips the parser;
    # each objective's direction comes from its metric's `lower_is_better`.
    if len(metrics) == 1:
        client.set_optimization_config(
            OptimizationConfig(objective=Objective(metric=metrics[0]))
        )
        return
    client.set_optimization_config(
        MultiObjectiveOptimizationConfig(
            objective=MultiObjective(
                objectives=[Objective(metric=metric) for metric in metrics]
            )
        )
    )


def create_default_client(config: dict[str, Any]) -> ax.Client:
    """Build an Ax `Client` configured from a sweep config alone."""
    from ax.api.client import Client

    client = Client()
    client.configure_experiment(parameters=sweep_config_to_search_space(config))
    configure_sweep_objective(client, config)
    return client
