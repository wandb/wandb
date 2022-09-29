__all__ = ["asset_registry"]

from .asset_registry import asset_registry

from .cpu import CPU
from .disk import Disk
from .gpu import GPU
from .gpu_apple import GPUApple
from .memory import Memory
from .network import Network
from .tpu import TPU
