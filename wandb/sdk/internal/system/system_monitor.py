import logging
import multiprocessing as mp
import queue
import threading
from typing import TYPE_CHECKING, List, Optional, Union

from .assets.asset_registry import asset_registry
from .assets.interfaces import Asset, Interface
from .system_info import SystemInfo

if TYPE_CHECKING:
    from wandb.proto.wandb_telemetry_pb2 import TelemetryRecord
    from wandb.sdk.interface.interface import FilesDict
    from wandb.sdk.internal.settings_static import SettingsStatic


logger = logging.getLogger(__name__)


class AssetInterface:
    def __init__(self) -> None:
        self.metrics_queue: "queue.Queue[dict]" = queue.Queue()
        self.telemetry_queue: "queue.Queue[TelemetryRecord]" = queue.Queue()

    def publish_stats(self, stats: dict) -> None:
        self.metrics_queue.put(stats)

    def _publish_telemetry(self, telemetry: "TelemetryRecord") -> None:
        self.telemetry_queue.put(telemetry)

    def publish_files(self, files_dict: "FilesDict") -> None:
        pass


class SystemMonitor:
    # SystemMonitor is responsible for managing system metrics data.

    # if joining assets, wait for publishing_interval times this many seconds
    PUBLISHING_INTERVAL_DELAY_FACTOR = 2

    def __init__(
        self,
        settings: "SettingsStatic",
        interface: "Interface",
    ) -> None:

        self._shutdown_event: mp.synchronize.Event = mp.Event()
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

        # hardware assets
        self.assets: List["Asset"] = []
        for asset_class in asset_registry:
            self.assets.append(
                asset_class(
                    interface=self.asset_interface or self.backend_interface,
                    settings=settings,
                    shutdown_event=self._shutdown_event,
                )
            )

        # static system info, both hardware and software
        self.system_info: SystemInfo = SystemInfo(
            settings=settings, interface=interface
        )

    def aggregate_and_publish_asset_metrics(self) -> None:
        if self.asset_interface is None:
            return None
        # only extract as many items as are available in the queue at the moment
        size = self.asset_interface.metrics_queue.qsize()

        aggregated_metrics = {}
        for _ in range(size):
            item = self.asset_interface.metrics_queue.get()
            aggregated_metrics.update(item)

        if aggregated_metrics:
            self.backend_interface.publish_stats(aggregated_metrics)

    def publish_telemetry(self) -> None:
        if self.asset_interface is None:
            return None
        # get everything from the self.asset_interface.telemetry_queue,
        # merge into a single dictionary and publish on the backend_interface
        while not self.asset_interface.telemetry_queue.empty():
            telemetry_record = self.asset_interface.telemetry_queue.get()
            self.backend_interface._publish_telemetry(telemetry_record)

    def _start(self) -> None:
        logger.info("Starting system asset monitoring threads")
        for asset in self.assets:
            asset.start()

        # compatibility mode: join stats from different assets before publishing
        if not (self.join_assets and self.asset_interface is not None):
            return None

        # give the assets a chance to accumulate and publish their first stats
        # this will provide a constant offset for the following accumulation events below
        self._shutdown_event.wait(
            self.publishing_interval * self.PUBLISHING_INTERVAL_DELAY_FACTOR
        )

        logger.debug("Starting system metrics aggregation loop")

        while not self._shutdown_event.is_set():
            self.publish_telemetry()
            self.aggregate_and_publish_asset_metrics()
            self._shutdown_event.wait(self.publishing_interval)

        logger.debug("Finished system metrics aggregation loop")

        # try to publish the last batch of metrics + telemetry
        try:
            logger.debug("Publishing last batch of metrics")
            # publish telemetry
            self.publish_telemetry()
            self.aggregate_and_publish_asset_metrics()
        except Exception as e:
            logger.error(f"Error publishing last batch of metrics: {e}")

    def start(self) -> None:
        if self._process is None and not self._shutdown_event.is_set():
            logger.info("Starting system monitor")
            # self._process = mp.Process(target=self._start, name="SystemMonitor")
            self._process = threading.Thread(
                target=self._start, daemon=True, name="SystemMonitor"
            )
            self._process.start()

    def finish(self) -> None:
        if self._process is None:
            return None
        logger.info("Stopping system monitor")
        self._shutdown_event.set()
        for asset in self.assets:
            asset.finish()
        self._process.join()
        self._process = None

    def probe(self, publish: bool = True) -> None:
        logger.info("Collecting system info")
        # collect static info about the hardware from registered assets
        hardware_info: dict = {
            k: v for d in [asset.probe() for asset in self.assets] for k, v in d.items()
        }
        # collect static info about the software environment
        software_info: dict = self.system_info.probe()
        # merge the two dictionaries
        system_info = {**software_info, **hardware_info}
        logger.debug(system_info)
        logger.info("Finished collecting system info")

        if publish:
            logger.info("Publishing system info")
            self.system_info.publish(system_info)
            logger.info("Finished publishing system info")
