import datetime
import logging
import threading
from typing import (
    TYPE_CHECKING,
    Any,
    List,
    Optional,
    Protocol,
    TypeVar,
    runtime_checkable,
)

if TYPE_CHECKING:
    from typing import Deque

    from wandb.proto.wandb_telemetry_pb2 import TelemetryRecord
    from wandb.sdk.interface.interface import FilesDict
    from wandb.sdk.internal.settings_static import SettingsStatic

import psutil

TimeStamp = TypeVar("TimeStamp", bound=datetime.datetime)


logger = logging.getLogger(__name__)


class Metric(Protocol):
    """Base protocol for individual metrics."""

    name: str
    # samples: Sequence[Tuple[TimeStamp, Sample]]
    samples: "Deque[Any]"

    def sample(self) -> None:
        """Sample the metric."""
        ...  # pragma: no cover

    def clear(self) -> None:
        """Clear the samples."""
        ...  # pragma: no cover

    def aggregate(self) -> dict:
        """Aggregate the samples."""
        ...  # pragma: no cover


@runtime_checkable
class SetupTeardown(Protocol):
    """Protocol for classes that require setup and teardown."""

    def setup(self) -> None:
        """Extra setup required for the metric beyond __init__."""
        ...  # pragma: no cover

    def teardown(self) -> None:
        """Extra teardown required for the metric."""
        ...  # pragma: no cover


@runtime_checkable
class Asset(Protocol):
    """Base protocol encapsulate everything relating to an "Asset".

    An asset can be CPU, GPU, TPU, Network, I/O etc.
    """

    name: str
    metrics: List[Metric]
    metrics_monitor: "MetricsMonitor"

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...  # pragma: no cover

    @classmethod
    def is_available(cls) -> bool:
        """Check if the resource is available."""
        ...  # pragma: no cover

    def start(self) -> None:
        """Start monitoring the resource."""
        ...  # pragma: no cover

    def finish(self) -> None:
        """Finish monitoring the resource."""
        ...  # pragma: no cover

    def probe(self) -> dict:
        """Get static information about the resource."""
        ...  # pragma: no cover


class Interface(Protocol):
    def publish_stats(self, stats: dict) -> None: ...  # pragma: no cover

    def _publish_telemetry(
        self, telemetry: "TelemetryRecord"
    ) -> None: ...  # pragma: no cover

    def publish_files(self, files_dict: "FilesDict") -> None: ...  # pragma: no cover


class MetricsMonitor:
    """Takes care of collecting, sampling, serializing, and publishing a set of metrics."""

    def __init__(
        self,
        asset_name: str,
        metrics: List[Metric],
        interface: Interface,
        settings: "SettingsStatic",
        shutdown_event: threading.Event,
    ) -> None:
        self.metrics = metrics
        self.asset_name = asset_name
        self._interface = interface
        self._process: Optional[threading.Thread] = None
        self._shutdown_event: threading.Event = shutdown_event

        self.sampling_interval: float = float(
            max(
                0.1,
                settings.x_stats_sampling_interval,
            )
        )  # seconds
        self.samples_to_aggregate = 1

    def monitor(self) -> None:
        """Poll the Asset metrics."""
        while not self._shutdown_event.is_set():
            for _ in range(self.samples_to_aggregate):
                for metric in self.metrics:
                    try:
                        metric.sample()
                    except psutil.NoSuchProcess:
                        logger.info(f"Process {metric.name} has exited.")
                        self._shutdown_event.set()
                        break
                    except Exception as e:
                        logger.error(f"Failed to sample metric: {e}")
                self._shutdown_event.wait(self.sampling_interval)
                if self._shutdown_event.is_set():
                    break
            self.publish()

    def aggregate(self) -> dict:
        """Return a dict of metrics."""
        aggregated_metrics = {}
        for metric in self.metrics:
            try:
                serialized_metric = metric.aggregate()
                aggregated_metrics.update(serialized_metric)
                # aggregated_metrics = wandb.util.merge_dicts(
                #     aggregated_metrics, metric.serialize()
                # )
            except Exception as e:
                logger.error(f"Failed to serialize metric: {e}")
        return aggregated_metrics

    def publish(self) -> None:
        """Publish the Asset metrics."""
        try:
            aggregated_metrics = self.aggregate()
            if aggregated_metrics:
                self._interface.publish_stats(aggregated_metrics)
            for metric in self.metrics:
                metric.clear()
        except Exception as e:
            logger.error(f"Failed to publish metrics: {e}")

    def start(self) -> None:
        if (self._process is not None) or self._shutdown_event.is_set():
            return None

        thread_name = f"{self.asset_name[:15]}"  # thread names are limited to 15 chars
        try:
            for metric in self.metrics:
                if isinstance(metric, SetupTeardown):
                    metric.setup()
            self._process = threading.Thread(
                target=self.monitor,
                daemon=True,
                name=thread_name,
            )
            self._process.start()
            logger.info(f"Started {thread_name} monitoring")
        except Exception as e:
            logger.warning(f"Failed to start {thread_name} monitoring: {e}")
            self._process = None

    def finish(self) -> None:
        if self._process is None:
            return None

        thread_name = f"{self.asset_name[:15]}"
        try:
            self._process.join()
            logger.info(f"Joined {thread_name} monitor")
            for metric in self.metrics:
                if isinstance(metric, SetupTeardown):
                    metric.teardown()
        except Exception as e:
            logger.warning(f"Failed to finish {thread_name} monitoring: {e}")
        finally:
            self._process = None
