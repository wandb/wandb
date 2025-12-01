"""Defines a proxy server that spies on requests to the W&B backend."""

__all__ = (
    "spy_proxy",
    "WandbBackendProxy",
    "WandbBackendSpy",
)

from .proxy import WandbBackendProxy, spy_proxy
from .spy import WandbBackendSpy
