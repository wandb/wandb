import multiprocessing as mp
from atexit import register
from typing import TYPE_CHECKING, Optional

from .asset_registry import AssetRegistryBase

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.internal.settings_static import SettingsStatic


class AssetBase(AssetRegistryBase, register=False):
    def __init__(
        self,
        interface: "InterfaceQueue",
        settings: "SettingsStatic",
        shutdown_event: mp.Event,
    ) -> None:
        self._interface = interface
        self._process: Optional[mp.Process] = None
        self._shutdown_event: mp.Event = shutdown_event

        self.sampling_interval = max(
            0.5, settings._stats_sample_rate_seconds
        )  # seconds
        # The number of samples to aggregate (e.g. average or compute max/min etc)
        # before publishing; defaults to 15; valid range: [2:30]
        self.samples_to_aggregate = min(30, max(2, settings._stats_samples_to_average))
        self.name = self.__class__.__name__.lower()
        self.metrics = []

    def monitor(self) -> None:
        """Poll the Asset metrics"""
        while not self._shutdown_event.is_set():
            for _ in range(self.samples_to_aggregate):
                for metric in self.metrics:
                    metric.sample()
                self._shutdown_event.wait(self.sampling_interval)
                if self._shutdown_event.is_set():
                    break
            self.publish()

    def serialize(self) -> dict:
        """Return a dict of metrics"""
        serialized_metrics = {}
        for metric in self.metrics:
            serialized_metrics.update(metric.serialize())
        return serialized_metrics

    def publish(self) -> None:
        """Publish the Asset metrics"""
        self._interface.publish_stats(self.serialize())
        for metric in self.metrics:
            metric.clear()

    def start(self) -> None:
        if self.metrics and self._process is None and not self._shutdown_event.is_set():
            self._process = mp.Process(target=self.monitor)
            self._process.start()

    def finish(self) -> None:
        if self._process is not None:
            self._process.join()
            self._process = None
