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
    _hide: Optional[bool]
    _summary: Optional[Sequence[str]]

    def __init__(
        self,
        name: str,
        step_metric: str = None,
        step_sync: bool = None,
        hide: bool = None,
        summary: Sequence[str] = None,
        goal: str = None,
    ) -> None:
        self._callback = None
        self._name = name
        self._step_metric = step_metric
        self._step_sync = step_sync
        self._hide = hide
        self._summary = summary
        self._goal = goal

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
    def hide(self) -> Optional[bool]:
        return self._hide

    @property
    def goal(self) -> Optional[str]:
        return self._goal

    def _commit(self) -> None:
        m = pb.MetricRecord()
        if self._name.endswith("*"):
            m.glob_name = self._name
        else:
            m.name = self._name
        if self._step_metric:
            m.step_metric = self._step_metric
        if self._step_sync:
            m.step_sync = self._step_sync
        if self._hide:
            m.hide = self._hide
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
        if self._goal == "minimize":
            m.goal.type = m.goal.MINIMIZE
        if self._goal == "maximize":
            m.goal.type = m.goal.MAXIMIZE
        if self._callback:
            self._callback(m)
