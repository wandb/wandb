import threading
from collections import deque
from typing import TYPE_CHECKING, List, Optional

try:
    import psutil
except ImportError:
    psutil = None
from .aggregators import aggregate_last, aggregate_mean
from .asset_registry import asset_registry
from .interfaces import Interface, Metric, MetricsMonitor

if TYPE_CHECKING:
    from typing import Deque

    from wandb.sdk.internal.settings_static import SettingsStatic


# CPU Metrics


class ProcessCpuPercent:
    """CPU usage of the process in percent normalized by the number of CPUs."""

    # name = "process_cpu_percent"
    name = "cpu"

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples: Deque[float] = deque([])
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

    def aggregate(self) -> dict:
        # todo: create a statistics class with helper methods to compute
        #      mean, median, min, max, etc.
        if not self.samples:
            return {}
        aggregate = aggregate_mean(self.samples)
        return {self.name: aggregate}


class CpuPercent:
    """CPU usage of the system in percent per core."""

    name = "cpu.{i}.cpu_percent"

    def __init__(self, interval: Optional[float] = None) -> None:
        self.samples: Deque[List[float]] = deque([])
        self.interval = interval

    def sample(self) -> None:
        self.samples.append(psutil.cpu_percent(interval=self.interval, percpu=True))

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        num_cpu = len(self.samples[0])
        cpu_metrics = {}
        for i in range(num_cpu):
            aggregate_i = aggregate_mean([sample[i] for sample in self.samples])
            cpu_metrics[self.name.format(i=i)] = aggregate_i

        return cpu_metrics


class ProcessCpuThreads:
    """Number of threads used by the process."""

    name = "proc.cpu.threads"

    def __init__(self, pid: int) -> None:
        self.samples: Deque[int] = deque([])
        self.pid = pid
        self.process: Optional[psutil.Process] = None

    def sample(self) -> None:
        if self.process is None:
            self.process = psutil.Process(self.pid)

        self.samples.append(self.process.num_threads())

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        return {self.name: aggregate_last(self.samples)}


@asset_registry.register
class CPU:
    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: threading.Event,
    ) -> None:
        self.name: str = self.__class__.__name__.lower()
        self.metrics: List[Metric] = [
            ProcessCpuPercent(settings._stats_pid),
            CpuPercent(),
            ProcessCpuThreads(settings._stats_pid),
        ]
        self.metrics_monitor: MetricsMonitor = MetricsMonitor(
            self.name,
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )

    @classmethod
    def is_available(cls) -> bool:
        return psutil is not None

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
