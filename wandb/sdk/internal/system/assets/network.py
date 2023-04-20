import threading
from collections import deque
from typing import TYPE_CHECKING, List

try:
    import psutil
except ImportError:
    psutil = None

from .aggregators import aggregate_mean
from .asset_registry import asset_registry
from .interfaces import Interface, Metric, MetricsMonitor

if TYPE_CHECKING:
    from typing import Deque

    from wandb.sdk.internal.settings_static import SettingsStatic


class NetworkSent:
    """Network bytes sent."""

    name = "network.sent"
    samples: "Deque[float]"

    def __init__(self) -> None:
        self.samples = deque([])
        self.sent_init = psutil.net_io_counters().bytes_sent

    def sample(self) -> None:
        self.samples.append(psutil.net_io_counters().bytes_sent - self.sent_init)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        aggregate = aggregate_mean(self.samples)
        # todo: this is an adapter for the legacy metrics system
        # return {"network": {self.name: aggregate}}
        return {self.name: aggregate}


class NetworkRecv:
    """Network bytes received."""

    name = "network.recv"
    samples: "Deque[float]"

    def __init__(self) -> None:
        self.samples = deque([])
        self.recv_init = psutil.net_io_counters().bytes_recv

    def sample(self) -> None:
        self.samples.append(psutil.net_io_counters().bytes_recv - self.recv_init)

    def clear(self) -> None:
        self.samples.clear()

    def aggregate(self) -> dict:
        if not self.samples:
            return {}
        aggregate = aggregate_mean(self.samples)
        # todo: this is an adapter for the legacy metrics system
        # return {"network": {self.name: aggregate}}

        return {self.name: aggregate}


@asset_registry.register
class Network:
    def __init__(
        self,
        interface: "Interface",
        settings: "SettingsStatic",
        shutdown_event: threading.Event,
    ) -> None:
        self.name = self.__class__.__name__.lower()
        self.metrics: List[Metric] = [
            NetworkSent(),
            NetworkRecv(),
        ]
        self.metrics_monitor = MetricsMonitor(
            self.name,
            self.metrics,
            interface,
            settings,
            shutdown_event,
        )

    def start(self) -> None:
        self.metrics_monitor.start()

    def finish(self) -> None:
        self.metrics_monitor.finish()

    @classmethod
    def is_available(cls) -> bool:
        """Return a new instance of the CPU metrics."""
        return psutil is not None

    def probe(self) -> dict:
        """Return a dict of the hardware information."""
        # net_if_addrs = psutil.net_if_addrs()

        # return {
        #     self.name: {
        #         "interfaces": {
        #             k: {
        #                 "addresses": [
        #                     {
        #                         "address": v.address,
        #                         "netmask": v.netmask,
        #                         "broadcast": v.broadcast,
        #                         "ptp": v.ptp,
        #                     }
        #                     for v in v
        #                 ]
        #             }
        #             for k, v in net_if_addrs.items()
        #         }
        #     }
        # }
        return {}
