__all__ = [
    "GPU",
]


from typing import List

from ..protocols import Metric


class GPU:
    name: str
    is_available: bool = False
    metrics: List[Metric]

    def probe(self) -> dict:
        return {}

    def poll(self) -> None:
        """Poll the NVIDIA GPU metrics"""
        pass

    def serialize(self) -> dict:
        """Serialize the metrics"""
        return {}
