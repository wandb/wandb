from typing import Sequence, List, Optional, Union, Any, Dict
from enum import Enum
from numbers import Number
import numpy as np
import datetime

from pydantic import BaseModel, Field
from .config import SweepConfig
from ._types import floating


class RunState(str, Enum):
    pending = "pending"
    running = "running"
    finished = "finished"
    killed = "killed"
    crashed = "crashed"
    failed = "failed"
    preempted = "preempted"
    preempting = "preempting"


def is_number(x: Any) -> bool:
    """Check if a value is a finite number."""
    try:
        return (
            np.isscalar(x)
            and np.isfinite(x)
            and isinstance(x, Number)
            and not isinstance(x, bool)
        )
    except TypeError:
        return False


class SweepRun(BaseModel):
    """A wandb Run that is part of a Sweep.

    >>> run = SweepRun(
    ...   name="my_run",
    ...   state=RunState.running,
    ...   config={"a": {"value": 1}},
    ... )

    Args:
        name: Name of the run.
        state: State of the run.
        config: `dict` representation of the run's wandb.config.
        summaryMetrics: `dict` of summary statistics for the run.
        history: List of dicts containing the arguments to calls of wandb.log made during the run.
        search_info: Dict containing information produced by the search algorithm.
        early_terminate_info: Dict containing information produced by the early terminate algorithm.
        stopped: Whether the run was stopped in the sweep
        shouldStop: Whether the run should stop in the sweep
        heartbeat_at: The last time the backend received a heart beat from the run
        exitcode: The exitcode of the process that trained the run
        running: Whether the run is currently running
    """

    name: Optional[str] = None
    summary_metrics: Optional[dict] = Field(
        default_factory=lambda: {}, alias="summaryMetrics"
    )
    history: List[dict] = Field(default_factory=lambda: [], alias="sampledHistory")
    config: dict = Field(default_factory=lambda: {})
    state: RunState = RunState.pending
    search_info: Optional[Dict] = None
    early_terminate_info: Optional[Dict] = None
    stopped: bool = False
    should_stop: bool = Field(default=False, alias="shouldStop")
    heartbeat_at: Optional[datetime.datetime] = Field(default=None, alias="heartbeatAt")
    exitcode: Optional[int] = None
    running: Optional[bool] = None

    class Config:
        use_enum_values = True
        allow_population_by_field_name = True

    def metric_history(
        self, metric_name: str, filter_invalid: bool = False
    ) -> List[floating]:
        return [
            d[metric_name]
            for d in self.history
            if metric_name in d
            and not (filter_invalid and not is_number(d[metric_name]))
        ]

    def summary_metric(self, metric_name: str) -> floating:
        if self.summary_metrics is None:
            raise ValueError("this run has no summary metrics")
        if metric_name not in self.summary_metrics:
            raise KeyError(f"{metric_name} is not a summary metric of this run.")
        return self.summary_metrics[metric_name]

    def metric_extremum(self, metric_name: str, kind: str) -> floating:
        """Calculate the maximum or minimum value of a specified metric.

        >>> run = SweepRun(history=[{'a': 1}, {'b': 3}, {'a': 2, 'b': 4}], summary_metrics={'a': 50})
        >>> assert run.metric_extremum('a', 'maximum') == 50

        Args:
            metric_name: The name of the target metric.
            kind: What kind of extremum to get (either "maximum" or "minimum").

        Returns:
            The maximum or minimum metric.
        """

        cmp_func = np.max if kind == "maximum" else np.min
        try:
            summary_metric = [self.summary_metric(metric_name)]
        except KeyError:
            summary_metric = []
        all_metrics = self.metric_history(metric_name) + summary_metric

        if len(all_metrics) == 0:
            raise ValueError(f"Cannot extract metric {metric_name} from run")

        all_metrics = list(filter(is_number, all_metrics))

        if len(all_metrics) == 0:
            raise ValueError("Run does not have any finite metric values")

        return cmp_func(all_metrics)


def next_run(
    sweep_config: Union[dict, SweepConfig],
    runs: List[SweepRun],
    validate: bool = False,
    **kwargs,
) -> Optional[SweepRun]:
    return next_runs(sweep_config, runs, validate, 1, **kwargs)[0]


def next_runs(
    sweep_config: Union[dict, SweepConfig],
    runs: List[SweepRun],
    validate: bool = False,
    n: int = 1,
    **kwargs,
) -> Sequence[Optional[SweepRun]]:
    """Calculate the next runs in a sweep.

    >>> suggested_run = next_runs({
    ...    'method': 'grid',
    ...    'parameters': {'a': {'values': [1, 2, 3]}}
    ... }, [])
    >>> assert suggested_run[0].config['a']['value'] == 1

    Args:
        sweep_config: The config for the sweep.
        runs: List of runs in the sweep.
        validate: Whether to validate `sweep_config` against the SweepConfig JSONschema.
           If true, will raise a Validation error if `sweep_config` does not conform to
           the schema. If false, will attempt to run the sweep with an unvalidated schema.
        n: the number of runs to return

    Returns:
        The suggested runs.
    """

    from .grid_search import grid_search_next_runs
    from .random_search import random_search_next_runs
    from .bayes_search import bayes_search_next_runs

    # validate the sweep config
    if validate:
        sweep_config = SweepConfig(sweep_config)

    if "method" not in sweep_config:
        raise ValueError("Sweep config must contain method section")

    if "parameters" not in sweep_config:
        raise ValueError("Sweep config must contain parameters section")

    if not (
        isinstance(sweep_config["parameters"], dict)
        and len(sweep_config["parameters"]) > 0
    ):
        raise ValueError(
            "Parameters section of sweep config must be a dict of at least length 1"
        )

    method = sweep_config["method"]

    if method == "grid":
        return grid_search_next_runs(
            runs, sweep_config, validate=validate, n=n, **kwargs
        )
    elif method == "random":
        return random_search_next_runs(sweep_config, validate=validate, n=n)
    elif method == "bayes":
        return bayes_search_next_runs(
            runs, sweep_config, validate=validate, n=n, **kwargs
        )
    else:
        raise ValueError(
            f'Invalid search type {method}, must be one of ["grid", "random", "bayes"]'
        )


def stop_runs(
    sweep_config: Union[dict, SweepConfig],
    runs: List[SweepRun],
    validate: bool = False,
) -> List[SweepRun]:
    """Calculate the runs in a sweep to stop by early termination.

    >>> to_stop = stop_runs({
    ...    "method": "grid",
    ...    "metric": {"name": "loss", "goal": "minimize"},
    ...    "early_terminate": {
    ...        "type": "hyperband",
    ...        "max_iter": 5,
    ...        "eta": 2,
    ...        "s": 2,
    ...    },
    ...    "parameters": {"a": {"values": [1, 2, 3]}},
    ... }, [
    ...    SweepRun(
    ...        name="a",
    ...        state=RunState.finished,  # This is already stopped
    ...        history=[
    ...            {"loss": 10},
    ...            {"loss": 9},
    ...        ],
    ...    ),
    ...    SweepRun(
    ...        name="b",
    ...        state=RunState.running,  # This should be stopped
    ...        history=[
    ...            {"loss": 10},
    ...            {"loss": 10},
    ...        ],
    ...    ),
    ...    SweepRun(
    ...        name="c",
    ...        state=RunState.running,  # This passes band 1 but not band 2
    ...        history=[
    ...            {"loss": 10},
    ...            {"loss": 8},
    ...            {"loss": 8},
    ...        ],
    ...    ),
    ...    SweepRun(
    ...        name="d",
    ...        state=RunState.running,
    ...        history=[
    ...            {"loss": 10},
    ...            {"loss": 7},
    ...            {"loss": 7},
    ...        ],
    ...    ),
    ...    SweepRun(
    ...        name="e",
    ...        state=RunState.finished,
    ...        history=[
    ...            {"loss": 10},
    ...            {"loss": 6},
    ...            {"loss": 6},
    ...        ],
    ...    ),
    ...])


    Args:
        sweep_config: The config for the sweep.
        runs: List of runs in the sweep.
        validate: Whether to validate `sweep_config` against the SweepConfig JSONschema.
           If true, will raise a Validation error if `sweep_config` does not conform to
           the schema. If false, will attempt to run the sweep with an unvalidated schema.


    Returns:
        A list of the runs to stop.
    """

    from .hyperband_stopping import hyperband_stop_runs

    # validate the sweep config
    if validate:
        sweep_config = SweepConfig(sweep_config)

    if "metric" not in sweep_config:
        raise ValueError('early terminate requires "metric" section')

    if "early_terminate" not in sweep_config:
        raise ValueError('early terminate requires "early_terminate" section.')
    et_type = sweep_config["early_terminate"]["type"]

    if et_type == "hyperband":
        return hyperband_stop_runs(runs, sweep_config, validate=validate)
    else:
        raise ValueError(
            f'Invalid early stopping type {et_type}, must be one of ["hyperband"]'
        )
