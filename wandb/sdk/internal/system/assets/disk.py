import threading
from collections import deque
from typing import TYPE_CHECKING, List

try:
    import psutil
except ImportError:
    psutil = None

from .aggregators import aggregate_mean
from .asset_registry import asset_registry
from .interfaces import Interface, Metric, MetricsMonitor

if TYPE_CHECKING:
    from typing import Deque

    from wandb.sdk.internal.settings_static import SettingsStatic


class DiskUsage:
    """Total system disk usage in percent."""

    # name = "disk_usage"
    name = "disk"
    samples: "Deque[float]"

    def __init__(self) -> None:
        self.samples = deque([])

    def sample(self) -> None:
        self.samples.append(psutil.disk_usage("/").percent)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        aggregate = aggregate_mean(self.samples)
        return {self.name: aggregate}


@asset_registry.register
class Disk:
    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: threading.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics: List[Metric] = [DiskUsage()]
        self.metrics_monitor = MetricsMonitor(
            self.name,
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )

    @classmethod
    def is_available(cls) -> bool:
        """Return a new instance of the CPU metrics."""
        return psutil is not None

    def probe(self) -> dict:
        # total disk space:
        total = psutil.disk_usage("/").total / 1024 / 1024 / 1024
        # total disk space used:
        used = psutil.disk_usage("/").used / 1024 / 1024 / 1024
        return {self.name: {"total": total, "used": used}}

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()
