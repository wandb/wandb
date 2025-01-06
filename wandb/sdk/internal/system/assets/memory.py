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


class ProcessMemoryRSS:
    """Memory resident set size (RSS) in MB.

    RSS is the portion of memory occupied by a process that is held in main memory (RAM).
    """

    # name = "memory_rss"
    name = "proc.memory.rssMB"
    samples: "Deque[float]"

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.process: Optional[psutil.Process] = None
        self.samples = deque([])

    def sample(self) -> None:
        if self.process is None:
            self.process = psutil.Process(self.pid)

        self.samples.append(self.process.memory_info().rss / 1024 / 1024)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        aggregate = aggregate_mean(self.samples)
        return {self.name: aggregate}


class ProcessMemoryPercent:
    """Process memory usage in percent."""

    # name = "process_memory_percent"
    name = "proc.memory.percent"
    samples: "Deque[float]"

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.process: Optional[psutil.Process] = None
        self.samples = deque([])

    def sample(self) -> None:
        if self.process is None:
            self.process = psutil.Process(self.pid)

        self.samples.append(self.process.memory_percent())

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        aggregate = aggregate_mean(self.samples)
        return {self.name: aggregate}


class MemoryPercent:
    """Total system memory usage in percent."""

    # name = "memory_percent"
    name = "memory"
    samples: "Deque[float]"

    def __init__(self) -> None:
        self.samples = deque([])

    def sample(self) -> None:
        self.samples.append(psutil.virtual_memory().percent)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        aggregate = aggregate_mean(self.samples)
        return {self.name: aggregate}


class MemoryAvailable:
    """Total system memory available in MB."""

    # name = "memory_available"
    name = "proc.memory.availableMB"
    samples: "Deque[float]"

    def __init__(self) -> None:
        self.samples = deque([])

    def sample(self) -> None:
        self.samples.append(psutil.virtual_memory().available / 1024 / 1024)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        aggregate = aggregate_mean(self.samples)
        return {self.name: aggregate}


@asset_registry.register
class Memory:
    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: threading.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics: List[Metric] = [
            MemoryAvailable(),
            MemoryPercent(),
            ProcessMemoryRSS(settings.x_stats_pid),
            ProcessMemoryPercent(settings.x_stats_pid),
        ]
        self.metrics_monitor = MetricsMonitor(
            self.name,
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    @classmethod
    def is_available(cls) -> bool:
        """Return a new instance of the CPU metrics."""
        return psutil is not None

    def probe(self) -> dict:
        """Return a dict of the hardware information."""
        # total available memory in gigabytes
        return {
            "memory": {
                "total": psutil.virtual_memory().total,
            }
        }
