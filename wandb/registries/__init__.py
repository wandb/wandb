"""Public API for W&B Registries.

This module provides the primary interface for interacting with W&B Registries.
"""

__all__ = [
    "Registry",
    "Registries",
]

from .registries_search import Registries
from .registry import Registry
