import os
from collections import deque
from typing import List

import psutil

from ..protocols import Metric

# CPU Metrics


class ProcessCpuPercent(Metric):
    name = "process_cpu_percent"
    metric_type = "gauge"

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.readings = []

    def poll(self) -> None:
        self.readings.append(psutil.Process(self.pid).cpu_percent())


class CPU:
    name: str
    metrics: List[Metric]

    def poll(self) -> None:
        """Poll the CPU metrics"""
        pass
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
        pass
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
