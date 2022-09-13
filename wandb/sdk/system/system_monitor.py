import inspect
import multiprocessing as mp
from typing import TYPE_CHECKING, List

import wandb.sdk.system.assets as assets
from .interfaces import Asset

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.internal.settings_static import SettingsStatic


def is_asset(obj):
    return isinstance(obj, Asset)


class SystemMonitor:
    # A collections of assets
    def __init__(
        self,
        settings: "SettingsStatic",
        interface: "InterfaceQueue",
    ) -> None:

        self._shutdown_event: mp.Event = mp.Event()

        self.assets: List["Asset"] = []
        # todo? this doesn't work bc of class attributes vs instance attributes
        # known_assets = inspect.getmembers(assets, is_asset)
        known_assets = inspect.getmembers(assets, inspect.isclass)
        for (_, asset_class) in known_assets:
            # if not available, won't add to the list of assets
            if asset_class.is_available():
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
            asset.metrics_monitor.start()

    def finish(self) -> None:
        self._shutdown_event.set()
        for asset in self.assets:
            asset.metrics_monitor.finish()
