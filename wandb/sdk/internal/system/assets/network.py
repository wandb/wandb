import threading
import time
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


class NetworkTrafficSent:
    """Network traffic sent."""

    name = "network.upload_speed"
    samples: "Deque[float]"
    last_sample: float

    def __init__(self) -> None:
        self.upload_speed = psutil.net_io_counters().bytes_sent
        self.samples = deque([])
        self.upload_speed.sample()
        self.last_sample = self.upload_speed.samples[-1]
        self.initial_timestamp = time.time()

    def sample(self) -> None:
        self.upload_speed.sample()
        current_timestamp = time.time()
        current_sample = self.network_sent.samples[-1]
        delta_sent = (current_sample - self.last_sample) / (
            current_timestamp - self.initial_timestamp
        )  # this should be the difference in timestamps
        self.samples.append(delta_sent)
        self.last_sample = current_sample
        self.initial_timestamp = current_timestamp

    def clear(self) -> None:
        self.network_sent.clear()
        self.samples.clear()

    def aggregate(self) -> dict:
        return (
            {self.name: aggregate_mean(self.samples)}
            if self.samples
            else {self.name: 0}
        )


class NetworkTrafficReceived:
    """Network traffic received."""

    name = "network.download_speed"
    samples: "Deque[float]"

    def __init__(self) -> None:
        self.network_received = psutil.net_io_counters().bytes_recv
        self.samples = deque([])
        self.network_received.sample()
        self.last_sample = self.network_received.samples[-1]
        self.initial_timestamp = time.time()

    def sample(self) -> None:
        self.network_received.sample()
        current_timestamp = time.time()
        current_sample = self.network_received.samples[-1]
        delta_sent = (current_sample - self.last_sample) / (
            current_timestamp - self.initial_timestamp
        )
        self.samples.append(delta_sent)
        self.last_sample = current_sample
        self.initial_timestamp = current_timestamp

    def clear(self) -> None:
        self.network_received.clear()
        self.samples.clear()

    def aggregate(self) -> dict:
        return (
            {self.name: aggregate_mean(self.samples)}
            if self.samples
            else {self.name: 0}
        )


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
            NetworkTrafficSent(),
            NetworkTrafficReceived(),
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
