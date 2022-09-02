import multiprocessing as mp
from typing import TYPE_CHECKING, List

from .assets import AssetRegistry

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.internal.settings_static import SettingsStatic

    from .assets.asset_base import AssetBase


class SystemMonitor:
    # A collections of assets
    def __init__(
        self,
        settings: "SettingsStatic",
        interface: "InterfaceQueue",
    ) -> None:

        self._shutdown_event: mp.Event = mp.Event()

        self.assets: List["AssetBase"] = list(
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
