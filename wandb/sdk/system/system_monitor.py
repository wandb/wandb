import threading
from typing import List, Optional

from .assets.cpu import CPU
from .assets.gpu import GPU

from ..interface.interface_queue import InterfaceQueue
from ..internal.settings_static import SettingsStatic
from .protocols import Asset


class AssetRegistry:
    # todo: auto-discover assets instead of hard-coding them
    def __init__(self):
        known_assets = [
            CPU,
            GPU,
        ]
        self._assets: List[Asset] = []
        for asset in known_assets:
            if asset.is_available:
                self._assets.append(asset())

    def __repr__(self) -> str:
        return f"AssetRegistry({[asset.name for asset in self._assets]})"

    # iter interface
    def __iter__(self):
        return iter(self._assets)


class SystemMonitor:  # SystemMetrics?
    # A collections of assets
    def __init__(
        self,
        settings: SettingsStatic,
        interface: InterfaceQueue,
    ) -> None:

        self._thread: Optional[threading.Thread] = None
        self._shutdown: bool = False
        self._interface: InterfaceQueue = interface

        self.settings = settings

        self.assets: List[Asset] = list(AssetRegistry())

        self.hardware: List[dict] = [asset.probe() for asset in self.assets]

    def poll(self) -> None:
        while True:
            stats = self.stats()
            for stat, value in stats.items():
                if isinstance(value, (int, float)):
                    self.sampler[stat] = self.sampler.get(stat, [])
                    self.sampler[stat].append(value)
            self.samples += 1
            if self._shutdown or self.samples >= self.samples_to_average:
                self.flush()
                if self._shutdown:
                    break
            seconds = 0.0
            while seconds < self.sample_rate_seconds:
                time.sleep(0.1)
                seconds += 0.1
                if self._shutdown:
                    self.flush()  # type: ignore
                    return

        while True:
            for asset in self.assets:
                asset.poll()

    def poll_once(self) -> None:
        for asset in self.assets:
            asset.poll()

    # serialize
    def serialize(self) -> dict:
        return {asset.name: asset.serialize() for asset in self.assets}

    def start(self) -> None:
        if self._thread is None:
            self._shutdown = False
            self._thread = threading.Thread(
                name="SystemMonitorThread",
                target=self.poll,
                daemon=True,
            )
        if not self._thread.is_alive():
            self._thread.start()

    def finish(self) -> None:
        ...
