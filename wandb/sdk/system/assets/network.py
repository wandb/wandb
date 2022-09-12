import multiprocessing as mp
from collections import deque
from typing import TYPE_CHECKING, Deque, cast

import psutil

from ..protocols import MetricType
from .asset_base import AssetBase

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.internal.settings_static import SettingsStatic


class NetworkSent:
    # name = "network_sent"
    name = "sent"
    metric_type = cast("gauge", MetricType)
    samples: Deque[float]

    def __init__(self) -> None:
        self.samples = deque([])
        self.sent_init = psutil.net_io_counters().bytes_sent

    def sample(self) -> None:
        self.samples.append(psutil.net_io_counters().bytes_sent - self.sent_init)

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class NetworkRecv:
    # name = "network_recv"
    name = "recv"
    metric_type = cast("gauge", MetricType)
    samples: Deque[float]

    def __init__(self) -> None:
        self.samples = deque([])
        self.recv_init = psutil.net_io_counters().bytes_recv

    def sample(self) -> None:
        self.samples.append(psutil.net_io_counters().bytes_recv - self.recv_init)

    def clear(self) -> None:
        self.samples.clear()

    def serialize(self) -> dict:
        aggregate = round(sum(self.samples) / len(self.samples), 2)
        return {self.name: aggregate}


class Network(AssetBase):
    def __init__(
        self,
        interface: "InterfaceQueue",
        settings: "SettingsStatic",
        shutdown_event: mp.Event,
    ) -> None:
        super().__init__(interface, settings, shutdown_event)
        self.metrics = [
            NetworkSent(),
            NetworkRecv(),
        ]

    @classmethod
    def is_available(cls) -> bool:
        """Return a new instance of the CPU metrics"""
        return True if psutil else False

    def probe(self) -> dict:
        """Return a dict of the hardware information"""
        return {}

    def serialize(self) -> dict:
        """Return a dict of the metrics"""
        serialized_metrics = super().serialize()
        return {self.name: serialized_metrics}
