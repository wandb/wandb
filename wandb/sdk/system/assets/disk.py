import multiprocessing as mp
from collections import deque
from typing import TYPE_CHECKING, Deque, cast

import psutil

from ..interfaces import MetricType, MetricsMonitor

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.internal.settings_static import SettingsStatic


class DiskUsage:
    # name = "disk_usage"
    name = "disk"
    metric_type = cast("gauge", MetricType)
    samples: Deque[float]

    def __init__(self) -> None:
        self.samples = deque([])

    def sample(self) -> None:
        self.samples.append(psutil.disk_usage("/").percent)

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class Disk:
    def __init__(
        self,
        interface: "InterfaceQueue",
        settings: "SettingsStatic",
        shutdown_event: mp.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics = [DiskUsage()]
        self.metrics_monitor = MetricsMonitor(
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )

    @classmethod
    def is_available(cls) -> bool:
        """Return a new instance of the CPU metrics"""
        return True if psutil else False

    def probe(self) -> dict:
        return {}
