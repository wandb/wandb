from typing import Iterator, List, Type

from .interfaces import Asset


class AssetRegistry:
    def __init__(self) -> None:
        self._registry: List[Type[Asset]] = []

    def register(self, asset: Type[Asset]) -> Type[Asset]:
        self._registry.append(asset)
        return asset

    def __iter__(self) -> Iterator[Type[Asset]]:
        for asset in self._registry:
            if asset.is_available():
                yield asset


asset_registry = AssetRegistry()
