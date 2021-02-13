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
    _step: Optional[str]
    _auto_step: Optional[bool]
    _hide: Optional[bool]
    _summary: Optional[Sequence[str]]

    def __init__(
        self,
        name: str,
        step: str = None,
        auto_step: bool = None,
        hide: bool = None,
        summary: Sequence[str] = None,
    ) -> None:
        self._callback = None
        self._name = name
        self._step = step
        self._auto_step = auto_step
        self._hide = hide
        self._summary = summary

    def _set_callback(self, cb: Callable[[pb.MetricRecord], None]) -> None:
        self._callback = cb

    @property
    def name(self) -> str:
        return self._name

    @property
    def step(self) -> Optional[str]:
        return self._step

    @property
    def auto(self) -> Optional[bool]:
        return self._auto_step

    def _commit(self) -> None:
        mr = pb.MetricRecord()
        m = mr.update.add()
        if self._name.endswith("*"):
            m.glob_name = self._name
        else:
            m.name = self._name
        if self._step:
            m.step = self._step
        if self._auto_step:
            m.auto_step = self._auto_step
        if self._hide:
            m.hide = self._hide
        if self._summary:
            summary_set = set(self._summary)
            if "min" in summary_set:
                m.summary.min = True
            if "max" in summary_set:
                m.summary.max = True
        if self._callback:
            self._callback(mr)
