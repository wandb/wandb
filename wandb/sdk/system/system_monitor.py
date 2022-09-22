import multiprocessing as mp
from typing import TYPE_CHECKING, List

from wandb.sdk.system.assets import asset_registry
from wandb.sdk.system.assets.interfaces import Asset

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.internal.settings_static import SettingsStatic


class SystemMonitor:
    # A collections of assets
    def __init__(
        self,
        settings: "SettingsStatic",
        interface: "InterfaceQueue",
    ) -> None:

        self._shutdown_event: mp.Event = mp.Event()

        self.assets: List["Asset"] = []
        for asset_class in asset_registry:
            self.assets.append(
                asset_class(
                    interface=interface,
                    settings=settings,
                    shutdown_event=self._shutdown_event,
                )
            )

        self.hardware: List[dict] = [asset.probe() for asset in self.assets]

    def start(self) -> None:
        for asset in self.assets:
            asset.start()

    def finish(self) -> None:
        self._shutdown_event.set()
        for asset in self.assets:
            asset.finish()
