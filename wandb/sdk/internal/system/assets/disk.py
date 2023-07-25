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


class DiskIn:
    """Total system disk In."""

    name = "disk"
    samples: "Deque[float]"

    def __init__(self) -> None:
        self.samples = deque([])

    def sample(self) -> None:
        self.samples.append(psutil.disk_io_counters().read_count)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        aggregate = aggregate_mean(self.samples)
        return {self.name: aggregate}


class DiskOut:
    """Total system disk Out."""

    name = "disk"
    samples: "Deque[float]"

    def __init__(self) -> None:
        self.samples = deque([])

    def sample(self) -> None:
        self.samples.append(psutil.disk_io_counters().write_count)

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
        self.metrics: List[Metric] = [DiskUsage(), DiskIn(), DiskOut()]
        self.metrics_monitor = MetricsMonitor(
            self.name,
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )

    @classmethod
    def is_available(cls) -> bool:
        """Return a new instance of the disk metrics."""
        return psutil is not None

    def probe(self) -> dict:
        disk_usage = psutil.disk_usage("/")
        disk_io_counters = psutil.disk_io_counters()

        # Total disk space in gigabytes
        total = disk_usage.total / 1024 / 1024 / 1024

        # Disk space currently in use in gigabytes
        used = disk_usage.used / 1024 / 1024 / 1024

        # total disk in - number of bytes read in gigabytes
        disk_in = disk_io_counters.read_bytes / 1024 / 1024 / 1024

        # total disk out - number of bytes written in gigabytes
        disk_out = disk_io_counters.write_bytes / 1024 / 1024 / 1024

        return {
            self.name: {
                "total": total,
                "used": used,
                "disk i": disk_in,
                "disk o": disk_out,
            }
        }

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()
