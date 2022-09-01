import datetime
from typing import Deque, List, Tuple, TypeVar

try:
    from typing import Literal, Protocol, runtime_checkable
except ImportError:
    from typing_extensions import Literal, Protocol, runtime_checkable


from ..interface.interface_queue import InterfaceQueue


TimeStamp = TypeVar("TimeStamp", bound=datetime.datetime)
Reading = TypeVar("Reading", float, int, str, bytes, list, tuple, dict)
MetricType = Literal["counter", "gauge", "histogram", "summary"]
# MetricType = Literal["gauge"]


class Metric(Protocol):
    name: str
    # at first, we will only support the gauge type
    metric_type: MetricType
    #
    samples: Deque[Tuple[TimeStamp, Reading]]

    def sample(self) -> None:
        ...

    def flush(self) -> None:
        ...

    def serialize(self) -> dict:
        ...


@runtime_checkable
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
    sampling_interval: float = 1.0
    _interface: InterfaceQueue

    @classmethod
    def get_instance(cls) -> "Asset":
        """Get an instance of the resource if available"""
        ...

    def probe(self) -> dict:
        """Get static information about the resource"""
        ...

    def monitor(self) -> None:
        """Poll the resource metrics"""
        ...

    def serialize(self) -> dict:
        """Serialize the metrics"""
        ...

    def start(self) -> None:
        """Start the resource's internal process with the monitoring loop"""
        ...

    def finish(self) -> None:
        """Stop the resource's internal process with the monitoring loop"""
        ...
