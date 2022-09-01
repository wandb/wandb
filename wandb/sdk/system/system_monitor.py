import multiprocessing as mp
from typing import List, Optional

from ..interface.interface_queue import InterfaceQueue
from ..internal.settings_static import SettingsStatic
from .assets.cpu import CPU
from .assets.gpu import GPU
from .protocols import Asset


class AssetRegistry:
    # todo: auto-discover assets instead of hard-coding them
    def __init__(
        self,
        interface: InterfaceQueue,
        settings: SettingsStatic,
        shutdown_event: mp.Event,
    ) -> None:
        known_assets = [
            CPU,
            # GPU,
        ]
        self._assets: List[Asset] = []
        for asset in known_assets:
            # if not available, returns None
            asset_instance = asset.get_instance(
                interface=interface,
                settings=settings,
                shutdown_event=shutdown_event,
            )
            if asset_instance is not None:
                self._assets.append(asset_instance)

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

        self._shutdown_event: mp.Event = mp.Event()
        self._interface: InterfaceQueue = interface

        # self.settings = settings

        self.assets: List[Asset] = list(
            AssetRegistry(
                interface=interface,
                settings=settings,
                shutdown_event=self._shutdown_event,
            )
        )

        self.hardware: List[dict] = [asset.probe() for asset in self.assets]

    def poll_once(self) -> None:
        # fixme: rm, it's for debugging
        for asset in self.assets:
            asset.monitor()

    def start(self) -> None:
        for asset in self.assets:
            asset.start()

    def finish(self) -> None:
        self._shutdown_event.set()
        for asset in self.assets:
            asset.finish()
