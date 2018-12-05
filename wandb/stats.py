import collections
import os
from pynvml import *
import time
from numbers import Number
import threading
from wandb import util
from wandb import termlog
psutil = util.get_module("psutil")


class SystemStats(object):
    def __init__(self, run, api):
        try:
            nvmlInit()
            self.gpu_count = nvmlDeviceGetCount()
        except NVMLError as err:
            self.gpu_count = 0
        self.run = run
        self._api = api
        self.sampler = {}
        self.samples = 0
        self._shutdown = False
        if psutil:
            net = psutil.net_io_counters()
            self.network_init = {
                "sent": net.bytes_sent,
                "recv": net.bytes_recv
            }
        else:
            termlog(
                "psutil not installed, only GPU stats will be reported.  Install with pip install psutil")
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True

    def start(self):
        self._thread.start()

    @property
    def proc(self):
        return psutil.Process(pid=self.run.pid)

    @property
    def sample_rate_seconds(self):
        """Sample system stats every this many seconds, defaults to 2, min is 0.5"""
        return max(0.5, self._api.dynamic_settings["system_sample_seconds"])

    @property
    def samples_to_average(self):
        """The number of samples to average before pushing, defaults to 15 valid range (2:30)"""
        return min(30, max(2, self._api.dynamic_settings["system_samples"]))

    def _thread_body(self):
        while True:
            stats = self.stats()
            for stat, value in stats.items():
                if isinstance(value, Number):
                    self.sampler[stat] = self.sampler.get(stat, [])
                    self.sampler[stat].append(value)
            self.samples += 1
            if self._shutdown or self.samples >= self.samples_to_average:
                self.flush()
                if self._shutdown:
                    break
            seconds = 0
            while seconds < self.sample_rate_seconds:
                time.sleep(0.1)
                seconds += 0.1
                if self._shutdown:
                    break

    def shutdown(self):
        self._shutdown = True
        try:
            self._thread.join()
        # Incase we never start it
        except RuntimeError:
            pass

    def flush(self):
        stats = self.stats()
        for stat, value in stats.items():
            # TODO: a bit hacky, we assume all numbers should be averaged.  If you want
            # max for a stat, you must put it in a sub key, like ["network"]["sent"]
            if isinstance(value, Number):
                samples = list(self.sampler.get(stat, [stats[stat]]))
                stats[stat] = round(sum(samples) / len(samples), 2)
        self.run.events.track("system", stats, _wandb=True)
        self.samples = 0
        self.sampler = {}

    def stats(self):
        stats = {}
        for i in range(0, self.gpu_count):
            handle = nvmlDeviceGetHandleByIndex(i)
            try:
                util = nvmlDeviceGetUtilizationRates(handle)
                memory = nvmlDeviceGetMemoryInfo(handle)
                temp = nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)
                stats["gpu.{0}.{1}".format(i, "gpu")] = util.gpu
                stats["gpu.{0}.{1}".format(i, "memory")] = util.memory
                stats["gpu.{0}.{1}".format(
                    i, "memory_allocated")] = memory.used / memory.total * 100
                stats["gpu.{0}.{1}".format(i, "temp")] = temp
            except NVMLError as err:
                pass
        if psutil:
            net = psutil.net_io_counters()
            sysmem = psutil.virtual_memory()
            stats["cpu"] = psutil.cpu_percent()
            stats["memory"] = sysmem.percent
            stats["network"] = {
                "sent": net.bytes_sent - self.network_init["sent"],
                "recv": net.bytes_recv - self.network_init["recv"]
            }
            # TODO: maybe show other partitions, will likely need user to configure
            stats["disk"] = psutil.disk_usage('/').percent
            stats["proc.memory.availableMB"] = sysmem.available / 1048576.0
            try:
                stats["proc.memory.rssMB"] = self.proc.memory_info().rss / \
                    1048576.0
                stats["proc.memory.percent"] = self.proc.memory_percent()
                stats["proc.cpu.threads"] = self.proc.num_threads()
            except psutil.NoSuchProcess:
                pass
        return stats
