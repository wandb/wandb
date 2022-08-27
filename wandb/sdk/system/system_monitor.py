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
        interface: InterfaceQueue,
        assets: Optional[List[Asset]] = None,
    ) -> None:

        self.settings = settings

        default_assets = [
            CPU(),
            # GPU(),
            # TPU(),
            # IPU(),
            # Network(),
            # Disk(),
            # Memory(),
        ]
        self.assets: List[Asset] = default_assets + (assets or [])

    def poll(self) -> None:
        for asset in self.assets:
            asset.poll()

    # serialize
    def to_json(self) -> dict:
        combined_metrics = {}
        for asset in self.assets:
            combined_metrics.update(asset.to_json())

        return combined_metrics
