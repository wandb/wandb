import datetime
from collections import deque
from typing import List, Literal, Protocol, TypeVar

TimeStamp = TypeVar("TimeStamp", bound=datetime.datetime)
Reading = TypeVar("Reading", float, int, str, bytes, list, tuple, dict)
MetricType = Literal["counter", "gauge", "histogram", "summary"]


class Metric(Protocol):
    name: str
    # at first, we will only support the gauge type
    metric_type: MetricType
    #
    readings: deque[(TimeStamp, Reading)]

    def poll(self) -> None:
        ...


class Asset(Protocol):
    # Base protocol to encapsulate everything relating to e.g. CPU, GPU, TPU, Network, I/O etc.
    # A collection of metrics.
    # - Use typing.Protocol’s to define and gently enforce interfaces
    # - poll method to collect metrics with a customizable polling interval
    # - Auto-discover stuff at startup to track metrics automatically
    # - Provide a class method to (lazily) construct a resource from a Prometheus?
    #   (and later other providers?) endpoint: poll once
    name: str
    metrics: List[Metric]

    def poll(self) -> None:
        ...
        # for metric in self.metrics:
        #     metric.readings.append(metric.poll())

    def serialize(self) -> dict:
        ...
