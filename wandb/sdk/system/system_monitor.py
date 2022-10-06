import multiprocessing as mp
import queue
import threading
import time
from typing import TYPE_CHECKING, List, Optional, Union

from wandb.sdk.system.assets import asset_registry
from wandb.sdk.system.assets.interfaces import Asset, Interface

if TYPE_CHECKING:
    from wandb.proto.wandb_telemetry_pb2 import TelemetryRecord
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.internal.settings_static import SettingsStatic


class AssetInterface:
    def __init__(self):
        self.metrics_queue: "queue.Queue[dict]" = queue.Queue()
        self.telemetry_queue: "queue.Queue[dict]" = queue.Queue()

    def publish_stats(self, stats: dict) -> None:
        self.metrics_queue.put(stats)

    def _publish_telemetry(self, telemetry: "TelemetryRecord") -> None:
        self.telemetry_queue.put(telemetry)


class SystemMonitor:
    # SystemMonitor is responsible for managing system metrics data.

    # if joining assets, wait for publishing_interval times this many seconds
    PUBLISHING_INTERVAL_DELAY_FACTOR = 2

    def __init__(
        self,
        settings: "SettingsStatic",
        interface: "InterfaceQueue",
    ) -> None:

        self._shutdown_event: mp.Event = mp.Event()
        self._process: Optional[Union[mp.Process, threading.Thread]] = None

        # settings._stats_join_assets controls whether we should join stats from different assets
        # before publishing them to the backend. If set to False, we will publish stats from each
        # asset separately, using the backend interface. If set to True, we will aggregate stats from
        # all assets before publishing them, using an internal queue interface, and then publish
        # them using the interface to the backend.
        # This is done to improve compatibility with older versions of the backend as it used to
        # collect the names of the metrics to be displayed in the UI from the first stats message.

        # compute the global publishing interval if _stats_join_assets is requested
        sampling_interval: float = float(
            max(
                0.1,
                settings._stats_sample_rate_seconds,
            )
        )  # seconds
        # The number of samples to aggregate (e.g. average or compute max/min etc.)
        # before publishing; defaults to 15; valid range: [1:30]
        samples_to_aggregate: int = min(30, max(1, settings._stats_samples_to_average))
        self.publishing_interval: float = sampling_interval * samples_to_aggregate
        self.join_assets: bool = settings._stats_join_assets

        self.backend_interface = interface
        self.asset_interface: Optional[AssetInterface] = (
            AssetInterface() if self.join_assets else None
        )

        self._start_time_stamp = time.monotonic()

        self.assets: List["Asset"] = []
        for asset_class in asset_registry:
            self.assets.append(
                asset_class(
                    interface=self.asset_interface or self.backend_interface,
                    settings=settings,
                    shutdown_event=self._shutdown_event,
                )
            )

        self.hardware: List[dict] = [asset.probe() for asset in self.assets]

    def _start(self) -> None:
        for asset in self.assets:
            asset.start()

        # compatibility mode: join stats from different assets before publishing
        if self.join_assets and self.asset_interface is not None:
            # give the assets a chance to accumulate and publish their first stats
            # this will provide a constant offset for the following accumulation events below
            self._shutdown_event.wait(
                self.publishing_interval * self.PUBLISHING_INTERVAL_DELAY_FACTOR
            )

            def aggregate_and_publish_asset_metrics() -> None:
                # only extract as many items as are available in the queue at the moment
                size = self.asset_interface.metrics_queue.qsize()
                # print(f"WOKE UP, FELL OUT OF BED, DRAGGED A COMB ACROSS MY HEAD: {size}")

                serialized_metrics = {}
                for _ in range(size):
                    item = self.asset_interface.metrics_queue.get()
                    # print(f"::harvested:: {item}")
                    serialized_metrics.update(item)

                if serialized_metrics:
                    self.backend_interface.publish_stats(serialized_metrics)

            while not self._shutdown_event.is_set():
                aggregate_and_publish_asset_metrics()
                self._shutdown_event.wait(self.publishing_interval)

            # try to publish the last batch of metrics
            aggregate_and_publish_asset_metrics()

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
