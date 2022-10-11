import multiprocessing as mp
from collections import deque
from typing import TYPE_CHECKING, List

import psutil

from wandb.sdk.system.assets.asset_registry import asset_registry
from wandb.sdk.system.assets.interfaces import (
    Interface,
    Metric,
    MetricsMonitor,
    MetricType,
)

if TYPE_CHECKING:
    from typing import Deque

    from wandb.sdk.internal.settings_static import SettingsStatic


class DiskUsage:
    # name = "disk_usage"
    name = "disk"
    metric_type: MetricType = "gauge"
    samples: "Deque[float]"

    def __init__(self) -> None:
        self.samples = deque([])

    def sample(self) -> None:
        self.samples.append(psutil.disk_usage("/").percent)

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


@asset_registry.register
class Disk:
    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: mp.synchronize.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics: List[Metric] = [DiskUsage()]
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
        # total disk space:
        total = psutil.disk_usage("/").total / 1024 / 1024 / 1024
        # total disk space used:
        used = psutil.disk_usage("/").used / 1024 / 1024 / 1024
        return {self.name: {"total": total, "used": used}}

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()
