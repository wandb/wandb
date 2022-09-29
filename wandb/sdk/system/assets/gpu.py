import multiprocessing as mp
from collections import deque
from typing import TYPE_CHECKING, Deque, List, cast

from wandb.vendor.pynvml import pynvml

from .interfaces import MetricType, MetricsMonitor
from . import asset_registry

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.internal.settings_static import SettingsStatic


class GPUMemoryUtilization:
    # name = "memory_utilization"
    name = "memory"
    metric_type = cast("gauge", MetricType)
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: Deque[List[float]]

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        memory_utilization_rate = []
        device_count = pynvml.nvmlDeviceGetCount()
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            memory_utilization_rate.append(
                pynvml.nvmlDeviceGetUtilizationRates(handle).memory
            )
        self.samples.append(memory_utilization_rate)

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        # todo: create a statistics class with helper methods to compute
        #      mean, median, min, max, etc.
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class GPUMemoryAllocated:
    # name = "memory_allocated"
    name = "memoryAllocated"
    metric_type = cast("gauge", MetricType)
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: Deque[List[float]]

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        memory_allocated = []
        device_count = pynvml.nvmlDeviceGetCount()
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            memory_allocated.append(memory_info.used / memory_info.total * 100)
        self.samples.append(memory_allocated)

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        # todo: create a statistics class with helper methods to compute
        #      mean, median, min, max, etc.
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class GPUUtilization:
    # name = "gpu_utilization"
    name = "gpu"
    metric_type = cast("gauge", MetricType)
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: Deque[List[float]]

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        gpu_utilization_rate = []
        device_count = pynvml.nvmlDeviceGetCount()
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            gpu_utilization_rate.append(
                pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
            )
        self.samples.append(gpu_utilization_rate)

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class GPUTemperature:
    # name = "gpu_temperature"
    name = "temp"
    metric_type = cast("gauge", MetricType)
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: Deque[List[float]]

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        temperature = []
        device_count = pynvml.nvmlDeviceGetCount()
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            temperature.append(
                pynvml.nvmlDeviceGetTemperature(
                    handle,
                    pynvml.NVML_TEMPERATURE_GPU,
                )
            )
        self.samples.append(temperature)

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class GPUPowerUsage:
    # name = "power_usage"
    name = "powerWatts"
    metric_type = cast("gauge", MetricType)
    # samples: Deque[Tuple[datetime.datetime, float]]
    samples: Deque[List[float]]

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.samples = deque([])

    def sample(self) -> None:
        power_usage = []
        device_count = pynvml.nvmlDeviceGetCount()
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            power_usage.append(pynvml.nvmlDeviceGetPowerUsage(handle) / 1000)
        self.samples.append(power_usage)

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


@asset_registry.register
class GPU:
    def __init__(
        self,
        interface: "InterfaceQueue",
        settings: "SettingsStatic",
        shutdown_event: mp.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics = [
            GPUMemoryAllocated(settings._stats_pid),
            GPUMemoryUtilization(settings._stats_pid),
            GPUUtilization(settings._stats_pid),
            GPUTemperature(settings._stats_pid),
            GPUPowerUsage(settings._stats_pid),
        ]
        self.metrics_monitor = MetricsMonitor(
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )

    @classmethod
    def is_available(cls) -> bool:
        try:
            pynvml.nvmlInit()
            return True
        except pynvml.NVMLError_LibraryNotFound:
            return False
        except Exception:
            return False

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    def probe(self) -> dict:
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        devices = []
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            devices.append(
                {
                    "name": pynvml.nvmlDeviceGetName(handle),
                    "memory": {
                        "total": info.total,
                        "used": info.used,
                        "free": info.free,
                    },
                }
            )
        return {"type": "gpu", "devices": devices}
