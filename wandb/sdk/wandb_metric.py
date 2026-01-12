"""metric."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Callable

from wandb.proto import wandb_internal_pb2 as pb

logger = logging.getLogger("wandb")


class Metric:
    """Metric object."""

    _callback: Callable[[pb.MetricRecord], None] | None
    _name: str
    _step_metric: str | None
    _step_sync: bool | None
    _hidden: bool | None
    _summary: Sequence[str] | None
    _goal: str | None
    _overwrite: bool | None

    def __init__(
        self,
        name: str,
        step_metric: str | None = None,
        step_sync: bool | None = None,
        hidden: bool | None = None,
        summary: Sequence[str] | None = None,
        goal: str | None = None,
        overwrite: bool | None = None,
    ) -> None:
        self._callback = None
        self._name = name
        self._step_metric = step_metric
        # default to step_sync=True if step metric is set
        step_sync = step_sync if step_sync is not None else step_metric is not None
        self._step_sync = step_sync
        self._hidden = hidden
        self._summary = summary
        self._goal = goal
        self._overwrite = overwrite

    def _set_callback(self, cb: Callable[[pb.MetricRecord], None]) -> None:
        self._callback = cb

    @property
    def name(self) -> str:
        return self._name

    @property
    def step_metric(self) -> str | None:
        return self._step_metric

    @property
    def step_sync(self) -> bool | None:
        return self._step_sync

    @property
    def summary(self) -> tuple[str, ...] | None:
        if self._summary is None:
            return None
        return tuple(self._summary)

    @property
    def hidden(self) -> bool | None:
        return self._hidden

    @property
    def goal(self) -> str | None:
        goal_dict = dict(min="minimize", max="maximize")
        return goal_dict[self._goal] if self._goal else None

    def _commit(self) -> None:
        m = pb.MetricRecord()
        m.options.defined = True
        if self._name.endswith("*"):
            m.glob_name = self._name
        else:
            m.name = self._name
        if self._step_metric:
            m.step_metric = self._step_metric
        if self._step_sync:
            m.options.step_sync = self._step_sync
        if self._hidden:
            m.options.hidden = self._hidden
        if self._summary:
            summary_set = set(self._summary)
            if "min" in summary_set:
                m.summary.min = True
            if "max" in summary_set:
                m.summary.max = True
            if "mean" in summary_set:
                m.summary.mean = True
            if "last" in summary_set:
                m.summary.last = True
            if "copy" in summary_set:
                m.summary.copy = True
            if "none" in summary_set:
                m.summary.none = True
            if "best" in summary_set:
                m.summary.best = True
            if "first" in summary_set:
                m.summary.first = True
        if self._goal == "min":
            m.goal = m.GOAL_MINIMIZE
        if self._goal == "max":
            m.goal = m.GOAL_MAXIMIZE
        if self._overwrite:
            m._control.overwrite = self._overwrite
        if self._callback:
            self._callback(m)
