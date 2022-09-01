__all__ = [
    "CPU",
]

from collections import deque
import datetime
import multiprocessing as mp
import time
from typing import Deque, List, Optional, Tuple, cast, TYPE_CHECKING

import psutil

from ..protocols import Metric, MetricType

if TYPE_CHECKING:
    from ...interface.interface_queue import InterfaceQueue
    from ...internal.settings_static import SettingsStatic


# CPU Metrics


class ProcessCpuPercent:
    # name = "process_cpu_percent"
    name = "cpu"
    metric_type = cast("gauge", MetricType)
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: Deque[float]

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        # todo: this is what we'd eventually want to do
        # self.samples.append(
        #     (
        #         datetime.datetime.utcnow(),
        #         psutil.Process(self.pid).cpu_percent(),
        #     )
        # )
        self.samples.append(psutil.Process(self.pid).cpu_percent())

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        # todo: create a statistics class with helper methods to compute
        #      mean, median, min, max, etc.
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class CpuPercent:
    # name = "cpu_percent"
    name = "gpu"
    metric_type = cast("gauge", MetricType)
    # samples: Deque[Tuple[datetime.datetime, List[float]]]
    samples: Deque[List[float]]

    def __init__(self, interval: Optional[float] = None) -> None:
        self.samples = deque([])
        self.interval = interval

    def sample(self) -> None:
        # self.samples.append(
        #     (
        #         datetime.datetime.utcnow(),
        #         psutil.cpu_percent(interval=self.interval, percpu=True),
        #     )
        # )
        self.samples.append(psutil.cpu_percent(interval=self.interval, percpu=True))  # type: ignore

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        # fixme: ugly adapter to test things out
        num_cpu = len(self.samples[0])
        cpu_metrics = {}
        for i in range(num_cpu):
            aggregate_i = round(
                sum(sample[i] for sample in self.samples) / len(self.samples), 2
            )
            # fixme: fix this adapter, it's for testing 🤮🤮🤮🤮🤮
            cpu_metrics[f"gpu.{i}.gpu"] = aggregate_i

        return cpu_metrics


class CPU:
    def __init__(
        self,
        interface: "InterfaceQueue",
        settings: "SettingsStatic",
        shutdown_event: mp.Event,
    ) -> None:
        self.name = "cpu"
        self.metrics = [
            ProcessCpuPercent(settings._stats_pid),
            CpuPercent(),
        ]
        # todo: metrics to consider:
        # self._cpu_percent = psutil.cpu_percent(interval=None, percpu=True)
        # self._cpu_times = psutil.cpu_times_percent(interval=None, percpu=True)
        # self._cpu_freq = psutil.cpu_freq(percpu=True)
        # self._cpu_count = psutil.cpu_count(logical=False)
        # self._cpu_count_logical = psutil.cpu_count(logical=True)
        # self._cpu_load_avg = os.getloadavg()
        # self._cpu_stats = psutil.cpu_stats()
        # self._cpu_times = psutil.cpu_times()
        # self._cpu_times_percent = psutil.cpu_times_percent()
        # self._cpu_times_percent_per_cpu = psutil.cpu_times_percent(percpu=True)
        # self._cpu_times_per_cpu = psutil.cpu_times(percpu=True)
        # self._cpu_freq = psutil.cpu_freq()
        # self._cpu_freq_per_cpu = psutil.cpu_freq(percpu=True)
        # self._cpu_percent = psutil.cpu_percent(interval=None)
        # self._cpu_percent_per_cpu = psutil.cpu_percent(interval=None, percpu=True)
        # self._cpu_percent_interval = psutil.cpu_percent(interval=1)
        # self._cpu_percent_interval_per_cpu = psutil.cpu_percent(interval=1, percpu=True)

        self.sampling_interval = max(
            0.5, settings._stats_sample_rate_seconds
        )  # seconds
        # The number of samples to aggregate (e.g. average or compute max/min etc)
        # before publishing; defaults to 15; valid range: [2:30]
        self.samples_to_aggregate = min(30, max(2, settings._stats_samples_to_average))
        self._interface = interface
        self._process: Optional[mp.Process] = None
        self._shutdown_event: mp.Event = shutdown_event

    @classmethod
    def get_instance(
        cls,
        interface: "InterfaceQueue",
        settings: "SettingsStatic",
        shutdown_event: mp.Event,
    ) -> "CPU":
        """Return a new instance of the CPU metrics"""
        is_available = True if psutil else False
        return (
            cls(
                interface=interface,
                settings=settings,
                shutdown_event=shutdown_event,
            )
            if is_available
            else None
        )

    def probe(self) -> dict:
        asset_info = {
            "cpu_count": psutil.cpu_count(logical=False),
            "cpu_count_logical": psutil.cpu_count(logical=True),
        }
        return asset_info

    def monitor(self) -> None:
        """Poll the CPU metrics"""
        while not self._shutdown_event.is_set():
            for _ in range(self.samples_to_aggregate):
                for metric in self.metrics:
                    metric.sample()
                self._shutdown_event.wait(self.sampling_interval)
                if self._shutdown_event.is_set():
                    break
            self.publish()

    def serialize(self) -> dict:
        """Return a dict of metrics"""
        serialized_metrics = {}
        for metric in self.metrics:
            serialized_metrics.update(metric.serialize())
        return serialized_metrics

    def publish(self) -> None:
        """Publish the CPU metrics"""
        self._interface.publish_stats(self.serialize())
        for metric in self.metrics:
            metric.clear()

    def start(self):
        if self._process is None and not self._shutdown_event.is_set():
            self._process = mp.Process(target=self.monitor)
            self._process.start()

    def finish(self):
        if self._process is not None:
            self._process.join()
            self._process = None
