import multiprocessing as mp
from collections import deque
from typing import TYPE_CHECKING, Deque, List, cast

import psutil

from ..protocols import MetricType
from .asset_base import AssetBase

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
        self.samples = deque([])

    def sample(self) -> None:
        self.samples.append(psutil.Process(self.pid).memory_info().rss / 1024 / 1024)

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
        self.samples = deque([])

    def sample(self) -> None:
        self.samples.append(psutil.Process(self.pid).memory_percent())

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


class Memory(AssetBase):
    def __init__(
        self,
        interface: "InterfaceQueue",
        settings: "SettingsStatic",
        shutdown_event: mp.Event,
    ) -> None:
        super().__init__(interface, settings, shutdown_event)
        self.metrics = [
            MemoryAvailable(),
            MemoryPercent(),
            ProcessMemoryRSS(settings._stats_pid),
            ProcessMemoryPercent(settings._stats_pid),
        ]

    @classmethod
    def is_available(cls) -> bool:
        """Return a new instance of the CPU metrics"""
        return True if psutil else False

    def probe(self) -> dict:
        """Return a dict of the hardware information"""
        return {}
