# TODO: for __init_subclass__ to work we need to import the relevant modules,
#      need to find a way to do this importlib.import_module()

from .asset_registry import AssetRegistry
from .cpu import CPU
from .disk import Disk
from .gpu import GPU
from .memory import Memory
from .network import Network
from .tpu import TPU

__all__ = [
    "AssetRegistry",
    "CPU",
    "Disk",
    "GPU",
    "Memory",
    "Network",
    "TPU",
]
