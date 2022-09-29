import multiprocessing as mp
import queue
import threading
import time
from typing import TYPE_CHECKING, List, Optional, Union

from wandb.sdk.system.assets import asset_registry
from wandb.sdk.system.assets.interfaces import Asset

if TYPE_CHECKING:
    from wandb.proto.wandb_telemetry_pb2 import TelemetryRecord
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.internal.settings_static import SettingsStatic


class AssetInterface:
    def __init__(self):
        self.metrics_queue = queue.Queue()
        self.telemetry_queue = queue.Queue()

    def publish_stats(self, stats: dict) -> None:
        self.metrics_queue.put(stats)

    def _publish_telemetry(self, telemetry: "TelemetryRecord") -> None:
        self.telemetry_queue.put(telemetry)


class SystemMonitor:
    # A collections of assets
    def __init__(
        self,
        settings: "SettingsStatic",
        interface: "InterfaceQueue",
    ) -> None:

        self._shutdown_event: mp.Event = mp.Event()
        self._process: Optional[Union[mp.Process, threading.Thread]] = None

        sampling_interval: float = float(
            max(
                0.1,
                settings._stats_sample_rate_seconds,
            )
        )  # seconds
        # The number of samples to aggregate (e.g. average or compute max/min etc.)
        # before publishing; defaults to 15; valid range: [2:30]
        samples_to_aggregate: int = min(30, max(2, settings._stats_samples_to_average))
        self.publish_interval: float = sampling_interval * samples_to_aggregate

        self.asset_interface: Optional[AssetInterface] = None
        if settings._stats_join_assets:
            self.asset_interface = AssetInterface()

        self._start_time_stamp = time.monotonic()

        self.assets: List["Asset"] = []
        for asset_class in asset_registry:
            self.assets.append(
                asset_class(
                    interface=self.asset_interface or interface,
                    settings=settings,
                    shutdown_event=self._shutdown_event,
                )
            )

        self.hardware: List[dict] = [asset.probe() for asset in self.assets]

    def _start(self) -> None:
        for asset in self.assets:
            asset.start()

        # give the assets a chance to accumulate and publish their first stats
        # this will provide a constant offset for the following accumulation events below
        self._shutdown_event.wait(self.publish_interval * 1.5)

        num_publish_intervals = 1
        while not self._shutdown_event.is_set():
            # allow for some wiggle room in the publish interval
            dt = (
                self.publish_interval * (num_publish_intervals - 0.5),
                self.publish_interval * (num_publish_intervals + 0.5),
            )

            self._shutdown_event.wait(self.publish_interval)
            # dt = delta * i - self._start_time_stamp

    def start(self) -> None:
        if self._process is None and not self._shutdown_event.is_set():
            # self._process = mp.Process(target=self._start)
            self._process = threading.Thread(target=self._start)
            self._process.start()

    def finish(self) -> None:
        self._shutdown_event.set()
        for asset in self.assets:
            asset.finish()
        self._process.join()
        self._process = None
