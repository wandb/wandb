import multiprocessing as mp
from collections import deque
from typing import TYPE_CHECKING, List, Optional

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


# CPU Metrics


class ProcessCpuPercent:
    """
    CPU usage of the process in percent normalized by the number of CPUs.
    """

    # name = "process_cpu_percent"
    name = "cpu"
    metric_type: MetricType = "gauge"
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: "Deque[float]"

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])
        self.process: Optional[psutil.Process] = None

    def sample(self) -> None:
        # todo: this is what we'd eventually want to do
        # self.samples.append(
        #     (
        #         datetime.datetime.utcnow(),
        #         psutil.Process(self.pid).cpu_percent(),
        #     )
        # )
        if self.process is None:
            self.process = psutil.Process(self.pid)

        self.samples.append(self.process.cpu_percent() / psutil.cpu_count())

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        # todo: create a statistics class with helper methods to compute
        #      mean, median, min, max, etc.
        if not self.samples:
            return {}
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class CpuPercent:
    """
    CPU usage of the system in percent per core.
    """

    name = "cpu.{i}.cpu_percent"
    metric_type: MetricType = "gauge"
    samples: "Deque[List[float]]"

    def __init__(self, interval: Optional[float] = None) -> None:
        self.samples = deque([])
        self.interval = interval

    def sample(self) -> None:
        self.samples.append(psutil.cpu_percent(interval=self.interval, percpu=True))

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        if not self.samples:
            return {}
        num_cpu = len(self.samples[0])
        cpu_metrics = {}
        for i in range(num_cpu):
            aggregate_i = round(
                sum(sample[i] for sample in self.samples) / len(self.samples), 2
            )
            cpu_metrics[self.name.format(i=i)] = aggregate_i

        return cpu_metrics


class ProcessCpuThreads:
    """
    Number of threads used by the process.
    """

    name = "proc.cpu.threads"
    metric_type: MetricType = "gauge"
    samples: "Deque[int]"

    def __init__(self, pid: int) -> None:
        self.samples = deque([])
        self.pid = pid
        self.process: Optional[psutil.Process] = None

    def sample(self) -> None:
        if self.process is None:
            self.process = psutil.Process(self.pid)

        self.samples.append(self.process.num_threads())

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        if not self.samples:
            return {}
        return {self.name: self.samples[-1]}


@asset_registry.register
class CPU:
    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: mp.synchronize.Event,
    ) -> None:
        self.name: str = self.__class__.__name__.lower()
        self.metrics: List[Metric] = [
            ProcessCpuPercent(settings._stats_pid),
            CpuPercent(),
            ProcessCpuThreads(settings._stats_pid),
        ]
        self.metrics_monitor: "MetricsMonitor" = MetricsMonitor(
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )

    @classmethod
    def is_available(cls) -> bool:
        return True if psutil else False

    def probe(self) -> dict:
        asset_info = {
            "cpu_count": psutil.cpu_count(logical=False),
            "cpu_count_logical": psutil.cpu_count(logical=True),
        }
        try:
            asset_info["cpu_freq"] = {
                "current": psutil.cpu_freq().current,
                "min": psutil.cpu_freq().min,
                "max": psutil.cpu_freq().max,
            }
            asset_info["cpu_freq_per_core"] = [
                {
                    "current": freq.current,
                    "min": freq.min,
                    "max": freq.max,
                }
                for freq in psutil.cpu_freq(percpu=True)
            ]
        except Exception:
            pass
        return asset_info

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()
