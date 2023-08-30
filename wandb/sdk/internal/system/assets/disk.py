import threading
from collections import deque
from typing import TYPE_CHECKING, List, Optional

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


class DiskUsagePercent:
    """Total system disk usage in percent."""

    name = "disk.{path}.usagePercent"
    samples: "Deque[float]"

    def __init__(self, paths: Optional[List[str]] = None) -> None:
        self.samples: Deque[List[float]] = deque([])
        self.paths = paths or ["/"]

    def sample(self) -> None:
        # self.samples.append(psutil.disk_usage("/").percent)
        disk_usage = []
        for path in self.paths:
            disk_usage.append(psutil.disk_usage(path).percent)
        self.samples.append(disk_usage)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        disk_metrics = {}
        for i, _path in enumerate(self.paths):
            aggregate_i = aggregate_mean([sample[i] for sample in self.samples])
            disk_metrics[self.name.format(path=i)] = aggregate_i

        return disk_metrics


class DiskUsage:
    """Total system disk usage in GB."""

    name = "disk.{path}.usageGB"
    samples: "Deque[float]"

    def __init__(self, paths: Optional[List[str]] = None) -> None:
        self.samples: Deque[List[float]] = deque([])
        self.paths = paths or ["/"]

    def sample(self) -> None:
        disk_usage = []
        for path in self.paths:
            disk_usage.append(psutil.disk_usage(path).used / 1024 / 1024 / 1024)
        self.samples.append(disk_usage)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        disk_metrics = {}
        for i, _path in enumerate(self.paths):
            aggregate_i = aggregate_mean([sample[i] for sample in self.samples])
            disk_metrics[self.name.format(path=i)] = aggregate_i

        return disk_metrics


class DiskIn:
    """Total system disk read in MB."""

    name = "disk.in"
    samples: "Deque[float]"

    def __init__(self) -> None:
        self.samples = deque([])
        self.read_init: Optional[int] = None

    def sample(self) -> None:
        if self.read_init is None:
            # initialize the read_init value on first sample
            self.read_init = psutil.disk_io_counters().read_bytes
        self.samples.append(
            (psutil.disk_io_counters().read_bytes - self.read_init) / 1024 / 1024
        )

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        aggregate = aggregate_mean(self.samples)
        return {self.name: aggregate}


class DiskOut:
    """Total system disk write in MB."""

    name = "disk.out"
    samples: "Deque[float]"

    def __init__(self) -> None:
        self.samples = deque([])
        self.write_init: Optional[int] = None

    def sample(self) -> None:
        if self.write_init is None:
            # init on first sample
            self.write_init = psutil.disk_io_counters().write_bytes
        self.samples.append(
            (psutil.disk_io_counters().write_bytes - self.write_init) / 1024 / 1024
        )

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
        self.metrics: List[Metric] = [
            DiskUsagePercent(list(settings._stats_disk_paths)),
            DiskUsage(list(settings._stats_disk_paths)),
            DiskIn(),
            DiskOut(),
        ]
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
        # total disk space in GB:
        total = psutil.disk_usage("/").total / 1024 / 1024 / 1024
        # total disk space used in GB:
        used = psutil.disk_usage("/").used / 1024 / 1024 / 1024

        return {self.name: {"total": total, "used": used}}

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()
