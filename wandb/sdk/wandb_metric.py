#
# -*- coding: utf-8 -*-
"""
metric.
"""

import logging

import wandb
from wandb.proto import wandb_internal_pb2 as pb


if wandb.TYPE_CHECKING:
    from typing import Callable, Optional, Sequence

logger = logging.getLogger("wandb")


class Metric(object):
    """
    Metric object
    """

    _callback: Optional[Callable[[pb.MetricRecord], None]]
    _name: str
    _x_axis: Optional[str]
    _auto: Optional[bool]
    _summary: Optional[Sequence[str]]

    def __init__(
        self,
        name: str,
        x_axis: str = None,
        auto: bool = None,
        summary: Sequence[str] = None,
    ) -> None:
        self._callback = None
        self._name = name
        self._x_axis = x_axis
        self._auto = auto
        self._summary = summary

    def _set_callback(self, cb: Callable[[pb.MetricRecord], None]) -> None:
        self._callback = cb

    @property
    def name(self) -> str:
        return self._name

    @property
    def x_axis(self) -> Optional[str]:
        return self._x_axis

    @property
    def auto(self) -> Optional[bool]:
        return self._auto

    def _commit(self) -> None:
        mr = pb.MetricRecord()
        m = mr.update.add()
        if self._name.endswith("*"):
            m.glob_name = self._name
        else:
            m.name = self._name
        if self._x_axis:
            m.x_axis = self._x_axis
        if self._auto:
            m.auto = self._auto
        if self._summary:
            summary_set = set(self._summary)
            if "min" in summary_set:
                m.summary.min = True
            if "max" in summary_set:
                m.summary.max = True
        if self._callback:
            self._callback(mr)
