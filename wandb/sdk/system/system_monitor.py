from collections import defaultdict
from typing import List, Optional

import wandb
from wandb.sdk.system.assets.cpu import CPU

from ..interface.interface_queue import InterfaceQueue
from .protocols import Asset


class SystemMonitor:  # SystemMetrics?
    # A collections of assets
    def __init__(
        self,
        settings: wandb.Settings,
        # interface: InterfaceQueue,
    ) -> None:

        self.settings = settings

        self.assets: List[Asset] = [
            CPU(),
            # GPU(),
            # TPU(),
            # IPU(),
            # Network(),
            # Disk(),
            # Memory(),
        ]

    def poll(self) -> None:
        for asset in self.assets:
            asset.poll()

    # serialize
    def serialize(self) -> dict:
        return {asset.name: asset.serialize() for asset in self.assets}
