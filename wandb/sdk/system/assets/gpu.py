from typing import List

from ..protocols import Metric


class GPU:
    name: str
    metrics: List[Metric]

    def poll(self) -> None:
        """Poll the NVIDIA GPU metrics"""
        pass
