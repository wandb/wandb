#
# -*- coding: utf-8 -*-
"""
metric.
"""

import logging

import wandb
from wandb.proto import wandb_internal_pb2 as pb


if wandb.TYPE_CHECKING:
    from typing import Callable, Optional, Sequence, Tuple

logger = logging.getLogger("wandb")


class Metric(object):
    """
    Metric object
    """

    _callback: Optional[Callable[[pb.MetricRecord], None]]
    _name: str
    _step_metric: Optional[str]
    _step_sync: Optional[bool]
    _hidden: Optional[bool]
    _summary: Optional[Sequence[str]]
    _goal: Optional[str]
    _overwrite: Optional[bool]

    def __init__(
        self,
        name: str,
        step_metric: str = None,
        step_sync: bool = None,
        hidden: bool = None,
        summary: Sequence[str] = None,
        goal: str = None,
        overwrite: bool = None,
    ) -> None:
        self._callback = None
        self._name = name
        self._step_metric = step_metric
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
    def step_metric(self) -> Optional[str]:
        return self._step_metric

    @property
    def step_sync(self) -> Optional[bool]:
        return self._step_sync

    @property
    def summary(self) -> Optional[Tuple[str, ...]]:
        if self._summary is None:
            return None
        return tuple(self._summary)

    @property
    def hidden(self) -> Optional[bool]:
        return self._hidden

    @property
    def goal(self) -> Optional[str]:
        goal_dict = dict(min="minimize", max="maximize")
        return goal_dict[self._goal] if self._goal else None

    def _commit(self) -> None:
        m = pb.MetricRecord()
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
            if "best" in summary_set:
                m.summary.best = True
        if self._goal == "min":
            m.goal = m.GOAL_MINIMIZE
        if self._goal == "max":
            m.goal = m.GOAL_MAXIMIZE
        if self._overwrite:
            m._control.overwrite = self._overwrite
        if self._callback:
            self._callback(m)
