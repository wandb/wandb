__all__ = [
    "GPU",
]


from typing import List

from wandb.vendor.pynvml import pynvml

from ..protocols import Metric


class GPU:
    name: str
    is_available: bool = False
    metrics: List[Metric]

    @classmethod
    def get_instance(cls):
        is_available = False
        if not is_available:
            return None
        return cls()

    def probe(self) -> dict:
        return {}

    def poll(self) -> None:
        """Poll the NVIDIA GPU metrics"""
        pass

    def serialize(self) -> dict:
        """Serialize the metrics"""
        return {}
