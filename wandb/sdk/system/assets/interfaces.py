import datetime
import multiprocessing as mp
import sys
import threading
from typing import List, Optional, TypeVar, TYPE_CHECKING, Union

if sys.version_info >= (3, 8):
    from typing import Literal, Protocol, runtime_checkable
else:
    from typing_extensions import Literal, Protocol, runtime_checkable

if sys.version_info >= (3, 9):
    from collections.abc import Sequence
else:
    from typing import Sequence

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.internal.settings_static import SettingsStatic

import wandb

TimeStamp = TypeVar("TimeStamp", bound=datetime.datetime)
Sample = TypeVar("Sample", float, int, str, bytes, list, tuple, dict)
MetricType = Literal["counter", "gauge", "histogram", "summary"]


class Metric(Protocol):
    """
    Base protocol for individual metrics
    """

    name: str
    # at first, we will only support the gauge type
    metric_type: MetricType
    # samples: Sequence[Tuple[TimeStamp, Sample]]
    samples: Sequence[Sample]

    def sample(self) -> None:
        ...

    def clear(self) -> None:
        ...

    def serialize(self) -> dict:
        ...


@runtime_checkable
class Asset(Protocol):
    """
    Base protocol to encapsulate everything relating to an "Asset"
    e.g. CPU, GPU, TPU, Network, I/O etc.
    """

    name: str
    metrics: List[Metric]
    metrics_monitor: "MetricsMonitor"

    @classmethod
    def is_available(cls) -> bool:
        """Check if the resource is available"""
        ...

    def start(self) -> None:
        """Start monitoring the resource"""
        ...

    def finish(self) -> None:
        """finish monitoring the resource"""
        ...

    def probe(self) -> dict:
        """Get static information about the resource"""
        ...


class MetricsMonitor:
    """
    Takes care of collecting, sampling, serializing, and publishing a set of metrics.
    """

    def __init__(
        self,
        metrics: List[Metric],
        interface: "InterfaceQueue",
        settings: "SettingsStatic",
        shutdown_event: mp.Event,
        # start_time,
    ) -> None:
        self.metrics = metrics
        self._interface = interface
        self._process: Optional[Union[mp.Process, threading.Thread]] = None
        self._shutdown_event: mp.Event = shutdown_event

        self.sampling_interval: float = float(
            max(
                0.1,
                settings._stats_sample_rate_seconds,
            )
        )  # seconds
        # The number of samples to aggregate (e.g. average or compute max/min etc.)
        # before publishing; defaults to 15; valid range: [2:30]
        self.samples_to_aggregate: int = min(
            30, max(2, settings._stats_samples_to_average)
        )
        # print(self.sampling_interval, self.samples_to_aggregate)

    def monitor(self) -> None:
        """Poll the Asset metrics"""
        while not self._shutdown_event.is_set():
            for _ in range(self.samples_to_aggregate):
                for metric in self.metrics:
                    metric.sample()
                self._shutdown_event.wait(self.sampling_interval)
                if self._shutdown_event.is_set():
                    break
            self.publish()

    def serialize(self) -> dict:
        """Return a dict of metrics"""
        # serialized_metrics = {"timestamp": time.monotonic() - self.start_time}
        serialized_metrics = {}
        for metric in self.metrics:
            serialized_metrics.update(metric.serialize())
            # serialized_metrics = wandb.util.merge_dicts(
            #     serialized_metrics, metric.serialize()
            # )
        return serialized_metrics

    def publish(self) -> None:
        """Publish the Asset metrics"""
        try:
            self._interface.publish_stats(self.serialize())
            for metric in self.metrics:
                metric.clear()
        except Exception as e:
            wandb.termerror(f"Failed to publish metrics: {e}", repeat=False)

    def start(self) -> None:
        if self._process is None and not self._shutdown_event.is_set():
            self._process = threading.Thread(target=self.monitor)
            self._process.start()

    def finish(self) -> None:
        if self._process is not None:
            self._process.join()
            self._process = None
