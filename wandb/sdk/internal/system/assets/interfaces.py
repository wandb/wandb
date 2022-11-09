import datetime
import logging
import multiprocessing as mp
import sys
import threading
from multiprocessing import synchronize
from typing import TYPE_CHECKING, Any, List, Optional, TypeVar, Union

if sys.version_info >= (3, 8):
    from typing import Protocol, runtime_checkable
else:
    from typing_extensions import Protocol, runtime_checkable

if TYPE_CHECKING:
    from typing import Deque
    from wandb.proto.wandb_telemetry_pb2 import TelemetryRecord
    from wandb.sdk.interface.interface import FilesDict
    from wandb.sdk.internal.settings_static import SettingsStatic

import wandb

TimeStamp = TypeVar("TimeStamp", bound=datetime.datetime)


logger = logging.getLogger(__name__)


class Metric(Protocol):
    """
    Base protocol for individual metrics
    """

    name: str
    # samples: Sequence[Tuple[TimeStamp, Sample]]
    samples: "Deque[Any]"

    def sample(self) -> None:
        ...  # pragma: no cover

    def clear(self) -> None:
        ...  # pragma: no cover

    def aggregate(self) -> dict:
        ...  # pragma: no cover


@runtime_checkable
class Asset(Protocol):
    """
    Base protocol to encapsulate everything relating to an "Asset"
    e.g. CPU, GPU, TPU, Network, I/O etc.
    """

    name: str
    metrics: List[Metric]
    metrics_monitor: "MetricsMonitor"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        ...  # pragma: no cover

    @classmethod
    def is_available(cls) -> bool:
        """Check if the resource is available"""
        ...  # pragma: no cover

    def start(self) -> None:
        """Start monitoring the resource"""
        ...  # pragma: no cover

    def finish(self) -> None:
        """finish monitoring the resource"""
        ...  # pragma: no cover

    def probe(self) -> dict:
        """Get static information about the resource"""
        ...  # pragma: no cover


class Interface(Protocol):
    def publish_stats(self, stats: dict) -> None:
        ...  # pragma: no cover

    def _publish_telemetry(self, telemetry: "TelemetryRecord") -> None:
        ...  # pragma: no cover

    def publish_files(self, files_dict: "FilesDict") -> None:
        ...  # pragma: no cover


class MetricsMonitor:
    """
    Takes care of collecting, sampling, serializing, and publishing a set of metrics.
    """

    def __init__(
        self,
        asset_name: str,
        metrics: List[Metric],
        interface: Interface,
        settings: "SettingsStatic",
        shutdown_event: synchronize.Event,
    ) -> None:
        self.metrics = metrics
        self.asset_name = asset_name
        self._interface = interface
        self._process: Optional[Union[mp.Process, threading.Thread]] = None
        self._shutdown_event: synchronize.Event = shutdown_event

        self.sampling_interval: float = float(
            max(
                0.1,
                settings._stats_sample_rate_seconds,
            )
        )  # seconds
        # The number of samples to aggregate (e.g. average or compute max/min etc.)
        # before publishing; defaults to 15; valid range: [1:30]
        self.samples_to_aggregate: int = min(
            30, max(1, settings._stats_samples_to_average)
        )

    def monitor(self) -> None:
        """Poll the Asset metrics"""
        while not self._shutdown_event.is_set():
            for _ in range(self.samples_to_aggregate):
                for metric in self.metrics:
                    try:
                        metric.sample()
                    except Exception as e:
                        wandb.termerror(f"Failed to sample metric: {e}", repeat=False)
                self._shutdown_event.wait(self.sampling_interval)
                if self._shutdown_event.is_set():
                    break
            self.publish()

    def aggregate(self) -> dict:
        """Return a dict of metrics"""
        aggregated_metrics = {}
        for metric in self.metrics:
            try:
                serialized_metric = metric.aggregate()
                aggregated_metrics.update(serialized_metric)
                # aggregated_metrics = wandb.util.merge_dicts(
                #     aggregated_metrics, metric.serialize()
                # )
            except Exception as e:
                wandb.termerror(f"Failed to serialize metric: {e}", repeat=False)
        return aggregated_metrics

    def publish(self) -> None:
        """Publish the Asset metrics"""
        try:
            aggregated_metrics = self.aggregate()
            if aggregated_metrics:
                self._interface.publish_stats(aggregated_metrics)
            for metric in self.metrics:
                metric.clear()
        except Exception as e:
            wandb.termerror(f"Failed to publish metrics: {e}", repeat=False)

    def start(self) -> None:
        if self._process is None and not self._shutdown_event.is_set():
            self._process = threading.Thread(
                target=self.monitor,
                daemon=True,
                name=f"{self.asset_name}",
            )
            self._process.start()
            logger.info(f"Started {self._process.name}")

    def finish(self) -> None:
        if self._process is not None:
            self._process.join()
            logger.info(f"Joined {self._process.name}")
            self._process = None
