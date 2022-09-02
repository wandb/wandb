from typing import Any, List


class AssetRegistryBase:

    REGISTRY: List = []

    @classmethod
    def __init_subclass__(cls, register: bool = True, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if register:
            cls.REGISTRY.append(cls)


class AssetRegistry:
    def __init__(self, **kwargs: Any) -> None:
        self._assets = []
        for asset in AssetRegistryBase.REGISTRY:
            # if not available, won't add to the list of assets
            if asset.is_available():
                self._assets.append(asset(**kwargs))

    def __repr__(self) -> str:
        return f"AssetRegistry({[asset.name for asset in self._assets]})"

    # iter interface
    def __iter__(self):
        return iter(self._assets)
