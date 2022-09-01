__all__ = [
    "GPU",
]


from typing import List, Optional

from wandb.vendor.pynvml import pynvml

from ..protocols import Metric
from ...interface.interface_queue import InterfaceQueue


class GPU:
    def __init__(self, interface: InterfaceQueue) -> None:
        self.interface = interface
        self.metrics: List[Metric] = []

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

    def start(self) -> None:
        pass

    def monitor(self) -> None:
        pass

    def finish(self) -> None:
        pass

    def serialize(self) -> dict:
        return {
            "type": "gpu",
            "metrics": [metric.serialize() for metric in self.metrics],
        }

    @classmethod
    def get_instance(cls, interface: InterfaceQueue) -> Optional["GPU"]:
        try:
            pynvml.nvmlInit()
            return cls(interface=interface)
        except pynvml.NVMLError_LibraryNotFound:
            return None
