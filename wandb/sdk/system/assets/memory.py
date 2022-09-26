import multiprocessing as mp
from collections import deque
from typing import TYPE_CHECKING, Deque, List, cast, Optional

import psutil

from .interfaces import MetricType, MetricsMonitor
from . import asset_registry

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.internal.settings_static import SettingsStatic


class ProcessMemoryRSS:
    # name = "memory_rss"
    name = "proc.memory.rssMB"

    metric_type = cast("gauge", MetricType)
    samples: Deque[float]

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

    def serialize(self) -> dict:
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class ProcessMemoryPercent:
    # name = "process_memory_percent"
    name = "proc.memory.percent"
    metric_type = cast("gauge", MetricType)
    samples: Deque[float]

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

    def serialize(self) -> dict:
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class MemoryPercent:
    # name = "memory_percent"
    name = "memory"
    metric_type = cast("gauge", MetricType)
    samples: Deque[List[float]]

    def __init__(self) -> None:
        self.samples = deque([])

    def sample(self) -> None:
        self.samples.append(psutil.virtual_memory().percent)

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class MemoryAvailable:
    # name = "memory_available"
    name = "proc.memory.availableMB"
    metric_type = cast("gauge", MetricType)
    samples: Deque[List[float]]

    def __init__(self) -> None:
        self.samples = deque([])

    def sample(self) -> None:
        self.samples.append(psutil.virtual_memory().available / 1024 / 1024)

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


@asset_registry.register
class Memory:
    def __init__(
        self,
        interface: "InterfaceQueue",
        settings: "SettingsStatic",
        shutdown_event: mp.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics = [
            MemoryAvailable(),
            MemoryPercent(),
            ProcessMemoryRSS(settings._stats_pid),
            ProcessMemoryPercent(settings._stats_pid),
        ]
        self.metrics_monitor = MetricsMonitor(
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
        """Return a new instance of the CPU metrics"""
        return True if psutil else False

    def probe(self) -> dict:
        """Return a dict of the hardware information"""
        return {}
