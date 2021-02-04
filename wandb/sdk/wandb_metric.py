#
# -*- coding: utf-8 -*-
"""
metric.
"""

import logging

import six
import wandb
from wandb.proto.wandb_internal_pb2 import MetricRecord, MetricValue


if wandb.TYPE_CHECKING:
    from typing import Callable, Optional, Sequence, Union

logger = logging.getLogger("wandb")


class Metric(object):
    """
    Metric object
    """

    _callback: Optional[Callable[[MetricRecord], None]]
    _metric: Union[str, Sequence[str]]
    _metric_value: MetricValue

    def __init__(self, metric: Union[str, Sequence[str]]) -> None:
        self._metric = metric
        self._metric_value = MetricValue()
        self._callback = None

    def _set_callback(self, cb: Callable[[MetricRecord], None]) -> None:
        self._callback = cb

    def _update_metric(self, metric_value: MetricValue) -> None:
        # Create a metric record update
        m = MetricRecord()
        mi = m.update.add()
        if isinstance(self._metric, six.string_types):
            mi.metric = self._metric
        else:
            mi.nested_metric.extend(self._metric)
        mi.val.MergeFrom(metric_value)

        # Sent it to the internal process
        if self._callback:
            self._callback(m)

        # Keep track of metric locally
        self._metric_value.MergeFrom(metric_value)

    def set_default_xaxis(self) -> "Metric":
        mv = MetricValue()
        mv.default_xaxis = True
        self._update_metric(mv)
        return self

    def set_summary(
        self, min: bool = None, max: bool = None, last: bool = None
    ) -> "Metric":
        mv = MetricValue()
        if min:
            mv.summary_min = True
        if max:
            mv.summary_max = True
        if last:
            mv.summary_last = True
        self._update_metric(mv)
        return self
