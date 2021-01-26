#
from __future__ import absolute_import

import json
import platform
import subprocess
import threading
import time

import psutil
import wandb
from wandb import util
from wandb.vendor.pynvml import pynvml

from . import tpu
from ..lib import telemetry


if wandb.TYPE_CHECKING:
    from typing import Dict, List, Optional, Union
    from ..interface.interface import BackendSender

    GPUHandle = object
    SamplerDict = Dict[str, List[float]]
    StatsDict = Dict[str, Union[float, Dict[str, float]]]


# TODO: hard coded max watts as 16.5, found this number in the SMC list.
# Eventually we can have the apple_gpu_stats binary query for this.
M1_MAX_POWER_WATTS = 16.5


def gpu_in_use_by_this_process(gpu_handle: GPUHandle) -> bool:
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

    our_pids = set([process.pid for process in our_processes])

    compute_pids = set(
        [
            process.pid
            for process in pynvml.nvmlDeviceGetComputeRunningProcesses(gpu_handle)
        ]
    )
    graphics_pids = set(
        [
            process.pid
            for process in pynvml.nvmlDeviceGetGraphicsRunningProcesses(gpu_handle)
        ]
    )

    pids_using_device = compute_pids | graphics_pids

    return len(pids_using_device & our_pids) > 0


class SystemStats(object):

    _pid: int
    _interface: BackendSender
    sampler: SamplerDict
    samples: int
    _thread: Optional[threading.Thread]
    gpu_count: int

    def __init__(self, pid: int, interface: BackendSender) -> None:
        try:
            pynvml.nvmlInit()
            self.gpu_count = pynvml.nvmlDeviceGetCount()
        except pynvml.NVMLError:
            self.gpu_count = 0
        # self.run = run
        self._pid = pid
        self._interface = interface
        self.sampler = {}
        self.samples = 0
        self._shutdown = False
        self._telem = telemetry.TelemetryRecord()
        if psutil:
            net = psutil.net_io_counters()
            self.network_init = {"sent": net.bytes_sent, "recv": net.bytes_recv}
        else:
            wandb.termlog(
                "psutil not installed, only GPU stats will be reported.  Install with pip install psutil"
            )
        self._thread = None
        self._tpu_profiler = None

        if tpu.is_tpu_available():
            try:
                self._tpu_profiler = tpu.get_profiler()
            except Exception as e:
                wandb.termlog("Error initializing TPUProfiler: " + str(e))

    def start(self) -> None:
        if self._thread is None:
            self._shutdown = False
            self._thread = threading.Thread(target=self._thread_body)
            self._thread.daemon = True
        if not self._thread.is_alive():
            self._thread.start()
        if self._tpu_profiler:
            self._tpu_profiler.start()

    @property
    def proc(self) -> psutil.Process:
        return psutil.Process(pid=self._pid)

    @property
    def sample_rate_seconds(self) -> float:
        """Sample system stats every this many seconds, defaults to 2, min is 0.5"""
        return 1
        # return max(0.5, self._api.dynamic_settings["system_sample_seconds"])

    @property
    def samples_to_average(self) -> int:
        """The number of samples to average before pushing, defaults to 15 valid range (2:30)"""
        return 4
        # return min(30, max(2, self._api.dynamic_settings["system_samples"]))

    def _thread_body(self) -> None:
        while True:
            stats = self.stats()
            for stat, value in stats.items():
                if isinstance(value, (int, float)):
                    self.sampler[stat] = self.sampler.get(stat, [])
                    self.sampler[stat].append(value)
            self.samples += 1
            if self._shutdown or self.samples >= self.samples_to_average:
                self.flush()
                if self._shutdown:
                    break
            seconds = 0.0
            while seconds < self.sample_rate_seconds:
                time.sleep(0.1)
                seconds += 0.1
                if self._shutdown:
                    self.flush()
                    return

    def shutdown(self) -> None:
        self._shutdown = True
        try:
            if self._thread is not None:
                self._thread.join()
        finally:
            self._thread = None
        if self._tpu_profiler:
            self._tpu_profiler.stop()

    def flush(self) -> None:
        stats = self.stats()
        for stat, value in stats.items():
            # TODO: a bit hacky, we assume all numbers should be averaged.  If you want
            # max for a stat, you must put it in a sub key, like ["network"]["sent"]
            if isinstance(value, (float, int)):
                # samples = list(self.sampler.get(stat, [stats[stat]]))
                samples = list(self.sampler.get(stat, [value]))
                stats[stat] = round(sum(samples) / len(samples), 2)
        # self.run.events.track("system", stats, _wandb=True)
        if self._interface:
            self._interface.publish_stats(stats)
        self.samples = 0
        self.sampler = {}

    def stats(self) -> StatsDict:
        stats: StatsDict = {}
        for i in range(0, self.gpu_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            try:
                utilz = pynvml.nvmlDeviceGetUtilizationRates(handle)
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                temp = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )
                in_use_by_us = gpu_in_use_by_this_process(handle)

                stats["gpu.{}.{}".format(i, "gpu")] = utilz.gpu
                stats["gpu.{}.{}".format(i, "memory")] = utilz.memory
                stats["gpu.{}.{}".format(i, "memoryAllocated")] = (
                    memory.used / float(memory.total)
                ) * 100
                stats["gpu.{}.{}".format(i, "temp")] = temp

                if in_use_by_us:
                    stats["gpu.process.{}.{}".format(i, "gpu")] = utilz.gpu
                    stats["gpu.process.{}.{}".format(i, "memory")] = utilz.memory
                    stats["gpu.process.{}.{}".format(i, "memoryAllocated")] = (
                        memory.used / float(memory.total)
                    ) * 100
                    stats["gpu.process.{}.{}".format(i, "temp")] = temp

                    # Some GPUs don't provide information about power usage
                try:
                    power_watts = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                    power_capacity_watts = (
                        pynvml.nvmlDeviceGetEnforcedPowerLimit(handle) / 1000.0
                    )
                    power_usage = (power_watts / power_capacity_watts) * 100

                    stats["gpu.{}.{}".format(i, "powerWatts")] = power_watts
                    stats["gpu.{}.{}".format(i, "powerPercent")] = power_usage

                    if in_use_by_us:
                        stats["gpu.process.{}.{}".format(i, "powerWatts")] = power_watts
                        stats[
                            "gpu.process.{}.{}".format(i, "powerPercent")
                        ] = power_usage

                except pynvml.NVMLError:
                    pass

            except pynvml.NVMLError:
                pass

        # On Apple M1 systems let's look for the gpu
        if (
            platform.system() == "Darwin"
            and platform.processor() == "arm"
            and self.gpu_count == 0
        ):
            try:
                out = subprocess.check_output([util.apple_gpu_stats_binary(), "--json"])
                m1_stats = json.loads(out.split(b"\n")[0])
                stats["gpu.0.gpu"] = m1_stats["utilization"]
                stats["gpu.0.memoryAllocated"] = m1_stats["mem_used"]
                stats["gpu.0.temp"] = m1_stats["temperature"]
                stats["gpu.0.powerWatts"] = m1_stats["power"]
                stats["gpu.0.powerPercent"] = (
                    m1_stats["power"] / M1_MAX_POWER_WATTS
                ) * 100
                # TODO: this stat could be useful eventually, it was consistently
                # 0 in my experimentation and requires a frontend change
                # so leaving it out for now.
                # stats["gpu.0.cpuWaitMs"] = m1_stats["cpu_wait_ms"]

                if self._interface and not self._telem.env.m1_gpu:
                    self._telem.env.m1_gpu = True
                    self._interface.publish_telemetry(self._telem)

            except (OSError, ValueError, TypeError, subprocess.CalledProcessError) as e:
                wandb.termwarn("GPU stats error {}".format(e))
                pass

        if psutil:
            net = psutil.net_io_counters()
            sysmem = psutil.virtual_memory()
            stats["cpu"] = psutil.cpu_percent()
            stats["memory"] = sysmem.percent
            stats["network"] = {
                "sent": net.bytes_sent - self.network_init["sent"],
                "recv": net.bytes_recv - self.network_init["recv"],
            }
            # TODO: maybe show other partitions, will likely need user to configure
            stats["disk"] = psutil.disk_usage("/").percent
            stats["proc.memory.availableMB"] = sysmem.available / 1048576.0
            try:
                stats["proc.memory.rssMB"] = self.proc.memory_info().rss / 1048576.0
                stats["proc.memory.percent"] = self.proc.memory_percent()
                stats["proc.cpu.threads"] = self.proc.num_threads()
            except psutil.NoSuchProcess:
                pass
        if self._tpu_profiler:
            stats["tpu"] = self._tpu_profiler.get_tpu_utilization()
        return stats
