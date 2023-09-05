import threading
from collections import deque
from typing import TYPE_CHECKING, List, Optional

try:
    import psutil
except ImportError:
    psutil = None

from wandb.errors.term import termwarn

from .aggregators import aggregate_mean
from .asset_registry import asset_registry
from .interfaces import Interface, Metric, MetricsMonitor

if TYPE_CHECKING:
    from typing import Deque

    from wandb.sdk.internal.settings_static import SettingsStatic


class DiskUsagePercent:
    """Total system disk usage in percent."""

    name = "disk.{path}.usagePercent"
    samples: "Deque[List[float]]"

    def __init__(self, paths: List[str]) -> None:
        self.samples = deque([])
        # check if we have access to the disk paths:
        self.paths: List[str] = []
        for path in paths:
            try:
                psutil.disk_usage(path)
                self.paths.append(path)
            except Exception as e:  # noqa
                termwarn(f"Could not access disk path {path}: {e}", repeat=False)

    def sample(self) -> None:
        # self.samples.append(psutil.disk_usage("/").percent)
        disk_usage: List[float] = []
        for path in self.paths:
            disk_usage.append(psutil.disk_usage(path).percent)
        if disk_usage:
            self.samples.append(disk_usage)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        disk_metrics = {}
        for i, _path in enumerate(self.paths):
            aggregate_i = aggregate_mean([sample[i] for sample in self.samples])
            # ugly hack to please the frontend:
            _path = _path.replace("/", "\\")
            disk_metrics[self.name.format(path=_path)] = aggregate_i

        return disk_metrics


class DiskUsage:
    """Total system disk usage in GB."""

    name = "disk.{path}.usageGB"
    samples: "Deque[List[float]]"

    def __init__(self, paths: List[str]) -> None:
        self.samples = deque([])
        # check if we have access to the disk paths:
        self.paths: List[str] = []
        for path in paths:
            try:
                psutil.disk_usage(path)
                self.paths.append(path)
            except Exception as e:  # noqa
                termwarn(f"Could not access disk path {path}: {e}", repeat=False)

    def sample(self) -> None:
        disk_usage: List[float] = []
        for path in self.paths:
            disk_usage.append(psutil.disk_usage(path).used / 1024 / 1024 / 1024)
        if disk_usage:
            self.samples.append(disk_usage)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        disk_metrics = {}
        for i, _path in enumerate(self.paths):
            aggregate_i = aggregate_mean([sample[i] for sample in self.samples])
            # ugly hack to please the frontend:
            _path = _path.replace("/", "\\")
            disk_metrics[self.name.format(path=_path)] = aggregate_i

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
        self.settings = settings
        self.metrics: List[Metric] = [
            DiskUsagePercent(list(settings._stats_disk_paths or ["/"])),
            DiskUsage(list(settings._stats_disk_paths or ["/"])),
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
        disk_paths = list(self.settings._stats_disk_paths or ["/"])
        disk_metrics = {}
        for disk_path in disk_paths:
            try:
                # total disk space in GB:
                total = psutil.disk_usage(disk_path).total / 1024 / 1024 / 1024
                # total disk space used in GB:
                used = psutil.disk_usage(disk_path).used / 1024 / 1024 / 1024
                disk_metrics[disk_path] = {
                    "total": total,
                    "used": used,
                }
            except Exception as e:  # noqa
                termwarn(f"Could not access disk path {disk_path}: {e}", repeat=False)

        return {self.name: disk_metrics}

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()
