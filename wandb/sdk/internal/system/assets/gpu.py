import logging
import threading
from collections import deque
from typing import TYPE_CHECKING, List

try:
    import psutil
except ImportError:
    psutil = None

from wandb.vendor.pynvml import pynvml

from .aggregators import aggregate_mean
from .asset_registry import asset_registry
from .interfaces import Interface, Metric, MetricsMonitor

if TYPE_CHECKING:
    from typing import Deque

    from wandb.sdk.internal.settings_static import SettingsStatic

    GPUHandle = object


logger = logging.getLogger(__name__)


def gpu_in_use_by_this_process(gpu_handle: "GPUHandle", pid: int) -> bool:
    if psutil is None:
        return False

    try:
        base_process = psutil.Process(pid=pid)
    except psutil.NoSuchProcess:
        # do not report any gpu metrics if the base process cant be found
        return False

    our_processes = base_process.children(recursive=True)
    our_processes.append(base_process)

    our_pids = {process.pid for process in our_processes}

    compute_pids = {
        process.pid
        for process in pynvml.nvmlDeviceGetComputeRunningProcesses(gpu_handle)  # type: ignore
    }
    graphics_pids = {
        process.pid
        for process in pynvml.nvmlDeviceGetGraphicsRunningProcesses(gpu_handle)  # type: ignore
    }

    pids_using_device = compute_pids | graphics_pids

    return len(pids_using_device & our_pids) > 0


class GPUMemoryUtilization:
    """GPU memory utilization in percent for each GPU."""

    # name = "memory_utilization"
    name = "gpu.{}.memory"
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: "Deque[List[float]]"

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        memory_utilization_rate = []
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            memory_utilization_rate.append(
                pynvml.nvmlDeviceGetUtilizationRates(handle).memory  # type: ignore
            )
        self.samples.append(memory_utilization_rate)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        stats = {}
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            samples = [sample[i] for sample in self.samples]
            aggregate = aggregate_mean(samples)
            stats[self.name.format(i)] = aggregate

            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            if gpu_in_use_by_this_process(handle, self.pid):
                stats[self.name.format(f"process.{i}")] = aggregate

        return stats


class GPUMemoryAllocated:
    """GPU memory allocated in percent for each GPU."""

    # name = "memory_allocated"
    name = "gpu.{}.memoryAllocated"
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: "Deque[List[float]]"

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        memory_allocated = []
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)  # type: ignore
            memory_allocated.append(memory_info.used / memory_info.total * 100)
        self.samples.append(memory_allocated)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        stats = {}
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            samples = [sample[i] for sample in self.samples]
            aggregate = aggregate_mean(samples)
            stats[self.name.format(i)] = aggregate

            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            if gpu_in_use_by_this_process(handle, self.pid):
                stats[self.name.format(f"process.{i}")] = aggregate

        return stats


class GPUMemoryAllocatedBytes:
    """GPU memory allocated in bytes for each GPU."""

    # name = "memory_allocated"
    name = "gpu.{}.memoryAllocatedBytes"
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: "Deque[List[float]]"

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        memory_allocated = []
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)  # type: ignore
            memory_allocated.append(memory_info.used)
        self.samples.append(memory_allocated)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        stats = {}
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            samples = [sample[i] for sample in self.samples]
            aggregate = aggregate_mean(samples)
            stats[self.name.format(i)] = aggregate

            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            if gpu_in_use_by_this_process(handle, self.pid):
                stats[self.name.format(f"process.{i}")] = aggregate

        return stats


class GPUUtilization:
    """GPU utilization in percent for each GPU."""

    # name = "gpu_utilization"
    name = "gpu.{}.gpu"
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: "Deque[List[float]]"

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        gpu_utilization_rate = []
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            gpu_utilization_rate.append(
                pynvml.nvmlDeviceGetUtilizationRates(handle).gpu  # type: ignore
            )
        self.samples.append(gpu_utilization_rate)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        stats = {}
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            samples = [sample[i] for sample in self.samples]
            aggregate = aggregate_mean(samples)
            stats[self.name.format(i)] = aggregate

            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            if gpu_in_use_by_this_process(handle, self.pid):
                stats[self.name.format(f"process.{i}")] = aggregate

        return stats


class GPUTemperature:
    """GPU temperature in Celsius for each GPU."""

    # name = "gpu_temperature"
    name = "gpu.{}.temp"
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: "Deque[List[float]]"

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        temperature = []
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            temperature.append(
                pynvml.nvmlDeviceGetTemperature(  # type: ignore
                    handle,
                    pynvml.NVML_TEMPERATURE_GPU,
                )
            )
        self.samples.append(temperature)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        stats = {}
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            samples = [sample[i] for sample in self.samples]
            aggregate = aggregate_mean(samples)
            stats[self.name.format(i)] = aggregate

            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            if gpu_in_use_by_this_process(handle, self.pid):
                stats[self.name.format(f"process.{i}")] = aggregate

        return stats


class GPUPowerUsageWatts:
    """GPU power usage in Watts for each GPU."""

    name = "gpu.{}.powerWatts"
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: "Deque[List[float]]"

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        power_usage = []
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            power_watts = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000  # type: ignore
            power_usage.append(power_watts)
        self.samples.append(power_usage)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        stats = {}
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            samples = [sample[i] for sample in self.samples]
            aggregate = aggregate_mean(samples)
            stats[self.name.format(i)] = aggregate

            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            if gpu_in_use_by_this_process(handle, self.pid):
                stats[self.name.format(f"process.{i}")] = aggregate

        return stats


class GPUPowerUsagePercent:
    """GPU power usage in percent for each GPU."""

    name = "gpu.{}.powerPercent"
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: "Deque[List[float]]"

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        power_usage = []
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            power_watts = pynvml.nvmlDeviceGetPowerUsage(handle)  # type: ignore
            power_capacity_watts = pynvml.nvmlDeviceGetEnforcedPowerLimit(handle)  # type: ignore
            power_usage.append((power_watts / power_capacity_watts) * 100)
        self.samples.append(power_usage)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        stats = {}
        device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
        for i in range(device_count):
            samples = [sample[i] for sample in self.samples]
            aggregate = aggregate_mean(samples)
            stats[self.name.format(i)] = aggregate

            handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
            if gpu_in_use_by_this_process(handle, self.pid):
                stats[self.name.format(f"process.{i}")] = aggregate

        return stats


@asset_registry.register
class GPU:
    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: threading.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics: List[Metric] = [
            GPUMemoryAllocated(settings._stats_pid),
            GPUMemoryAllocatedBytes(settings._stats_pid),
            GPUMemoryUtilization(settings._stats_pid),
            GPUUtilization(settings._stats_pid),
            GPUTemperature(settings._stats_pid),
            GPUPowerUsageWatts(settings._stats_pid),
            GPUPowerUsagePercent(settings._stats_pid),
        ]
        self.metrics_monitor = MetricsMonitor(
            self.name,
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )

    @classmethod
    def is_available(cls) -> bool:
        try:
            pynvml.nvmlInit()  # type: ignore
            return True
        except pynvml.NVMLError_LibraryNotFound:  # type: ignore
            return False
        except Exception as e:
            logger.error(f"Error initializing NVML: {e}")
            return False

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    def probe(self) -> dict:
        info = {}
        try:
            pynvml.nvmlInit()  # type: ignore
            # todo: this is an adapter for the legacy stats system:
            info["gpu"] = pynvml.nvmlDeviceGetName(pynvml.nvmlDeviceGetHandleByIndex(0))  # type: ignore
            info["gpu_count"] = pynvml.nvmlDeviceGetCount()  # type: ignore

            device_count = pynvml.nvmlDeviceGetCount()  # type: ignore
            devices = []
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)  # type: ignore
                gpu_info = pynvml.nvmlDeviceGetMemoryInfo(handle)  # type: ignore
                devices.append(
                    {
                        "name": pynvml.nvmlDeviceGetName(handle),
                        "memory_total": gpu_info.total,
                    }
                )
            info["gpu_devices"] = devices

        except pynvml.NVMLError:
            pass
        except Exception as e:
            logger.error(f"Error Probing GPU: {e}")

        return info
