from typing import List
from .interfaces import Asset


class AssetRegistry:
    def __init__(self) -> None:
        self._registry: List[Asset] = []

    def register(self, asset: Asset) -> Asset:
        self._registry.append(asset)
        return asset

    def __iter__(self):
        for asset in self._registry:
            if asset.is_available():
                yield asset


asset_registry = AssetRegistry()
