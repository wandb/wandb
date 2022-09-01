__all__ = [
    "CPU",
]

from collections import deque
import datetime
import multiprocessing as mp
import os
import time
from typing import Deque, List, Optional, Tuple, cast

import psutil

from ..protocols import Metric, MetricType
from ...interface.interface_queue import InterfaceQueue

# CPU Metrics


class ProcessCpuPercent:
    name = "process_cpu_percent"
    metric_type = cast("gauge", MetricType)
    readings: Deque[Tuple[datetime.datetime, float]]

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.readings = deque([])

    def sample(self) -> None:
        self.readings.append(
            (
                datetime.datetime.utcnow(),
                psutil.Process(self.pid).cpu_percent(),
            )
        )

    def serialize(self) -> dict:
        return {self.name: self.readings}


class CpuPercent:
    name = "cpu_percent"
    metric_type = cast("gauge", MetricType)
    readings: Deque[Tuple[datetime.datetime, float]]

    def __init__(self, interval: Optional[float] = None) -> None:
        self.readings = deque([])
        self.interval = interval

    def sample(self) -> None:
        self.readings.append(
            (
                datetime.datetime.utcnow(),
                psutil.cpu_percent(interval=self.interval, percpu=True),
            )
        )

    def serialize(self) -> dict:
        # return {
        #     self.name: {
        #         "type": self.metric_type,
        #         "value": self.readings[-1],
        #     }
        # }
        return {self.name: self.readings}


class CPU:
    def __init__(self, interface: InterfaceQueue) -> None:
        self.name = "cpu"
        self.metrics = [
            ProcessCpuPercent(os.getpid()),
            CpuPercent(),
        ]
        self.sampling_interval = 1  # seconds
        self._interface = interface
        self._process: Optional[mp.Process] = None
        self._shutdown: bool = False

    @classmethod
    def get_instance(cls, interface: InterfaceQueue) -> "CPU":
        """Return a new instance of the CPU metrics"""
        is_available = True if psutil else False
        return cls(interface=interface) if is_available else None

    def probe(self) -> dict:
        asset_info = {
            "num_cpus": psutil.cpu_count(logical=False),
        }
        return asset_info

    def monitor(self) -> None:
        """Poll the CPU metrics"""
        while not self._shutdown:
            for metric in self.metrics:
                metric.sample()
            time.sleep(self.sampling_interval)

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

    def serialize(self):
        """Return a dict of metrics"""
        return [metric.serialize() for metric in self.metrics]

        # return {
        #     "cpu_count": self._cpu_count,
        #     "cpu_count_logical": self._cpu_count_logical,
        #     "cpu_load_avg": self._cpu_load_avg,
        #     "cpu_stats": self._cpu_stats,
        #     "cpu_times": self._cpu_times,
        #     "cpu_times_percent": self._cpu_times_percent,
        #     "cpu_times_percent_per_cpu": self._cpu_times_percent_per_cpu,
        #     "cpu_times_per_cpu": self._cpu_times_per_cpu,
        #     "cpu_freq": self._cpu_freq,
        #     "cpu_freq_per_cpu": self._cpu_freq_per_cpu,
        #     "cpu_percent": self._cpu_percent,
        #     "cpu_percent_per_cpu": self._cpu_percent_per_cpu,
        #     "cpu_percent_interval": self._cpu_percent_interval,
        #     "cpu_percent_interval_per_cpu": self._cpu_percent_interval_per_cpu,
        # }

    def start(self):
        if self._process is None and not self._shutdown:
            self._process = mp.Process(target=self.monitor)
            self._process.start()

    def finish(self):
        if self._process is not None:
            self._shutdown = True
            # self._process.terminate()
            # self._process = None
