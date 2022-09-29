import multiprocessing as mp
import time
from typing import TYPE_CHECKING, List, Optional

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
        self._process: Optional[mp.Process] = None

        # self._start_time_stamp = time.monotonic()

        self.assets: List["Asset"] = []
        for asset_class in asset_registry:
            self.assets.append(
                asset_class(
                    interface=interface,
                    settings=settings,
                    shutdown_event=self._shutdown_event,
                    # start_time_stamp=self._start_time_stamp,
                )
            )

        self.hardware: List[dict] = [asset.probe() for asset in self.assets]

    def _start(self) -> None:
        for asset in self.assets:
            asset.start()

        # i = 0
        # while True:
        #     dt = delta * i - self._start_time_stamp

    def start(self) -> None:
        if self._process is None and not self._shutdown_event.is_set():
            self._process = mp.Process(target=self._start)
            self._process.start()

    def finish(self) -> None:
        self._shutdown_event.set()
        for asset in self.assets:
            asset.finish()
        self._process.join()
        self._process = None
