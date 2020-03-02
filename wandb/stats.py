import collections
import pynvml
import time
import os
from numbers import Number
import threading
from wandb import util
from wandb import termlog
psutil = util.get_module("psutil")


def gpu_in_use_by_this_process(gpu_handle):
    if not psutil:
        return False

    # NOTE: this optimizes for the case where wandb was initialized from
    # iniside the user script (i.e. `wandb.init()`). If we ran using
    # `wandb run` on the command line, the shell will be detected as the
    # parent, possible resulting in sibling processes being incorrectly
    # indentified as part of this process -- still better than not
    # detecting in-use gpus at all.
    base_process = psutil.Process().parent() or psutil.Process()

    our_processes = base_process.children(recursive=True)
    our_processes.append(base_process)

    our_pids = set([
        process.pid
        for process
        in our_processes
    ])

    compute_pids = set([
        process.pid
        for process
        in pynvml.nvmlDeviceGetComputeRunningProcesses(gpu_handle)
    ])
    graphics_pids = set([
        process.pid
        for process
        in pynvml.nvmlDeviceGetGraphicsRunningProcesses(gpu_handle)
    ])

    pids_using_device = compute_pids | graphics_pids

    return len(pids_using_device & our_pids) > 0


class SystemStats(object):
    def __init__(self, run, api):
        try:
            pynvml.nvmlInit()
            self.gpu_count = pynvml.nvmlDeviceGetCount()
        except pynvml.NVMLError as err:
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
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                in_use_by_us = gpu_in_use_by_this_process(handle)

                stats["gpu.{}.{}".format(i, "gpu")] = util.gpu
                stats["gpu.{}.{}".format(i, "memory")] = util.memory
                stats["gpu.{}.{}".format(
                    i, "memoryAllocated")] = (memory.used / float(memory.total)) * 100
                stats["gpu.{}.{}".format(i, "temp")] = temp

                if in_use_by_us:
                    stats["gpu.process.{}.{}".format(i, "gpu")] = util.gpu
                    stats["gpu.process.{}.{}".format(i, "memory")] = util.memory
                    stats["gpu.process.{}.{}".format(
                        i, "memoryAllocated")] = (memory.used / float(memory.total)) * 100
                    stats["gpu.process.{}.{}".format(i, "temp")] = temp

                    # Some GPUs don't provide information about power usage
                try:
                    power_watts = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                    power_capacity_watts = pynvml.nvmlDeviceGetEnforcedPowerLimit(handle) / 1000.0
                    power_usage = (power_watts / power_capacity_watts) * 100

                    stats["gpu.{}.{}".format(i, "powerWatts")] = power_watts
                    stats["gpu.{}.{}".format(i, "powerPercent")] = power_usage

                    if in_use_by_us:
                        stats["gpu.process.{}.{}".format(i, "powerWatts")] = power_watts
                        stats["gpu.process.{}.{}".format(i, "powerPercent")] = power_usage

                except pynvml.NVMLError as err:
                    pass

            except pynvml.NVMLError as err:
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
