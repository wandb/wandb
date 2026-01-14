"""Constants determining what IPC methods are supported."""

import socket

SUPPORTS_UNIX = hasattr(socket, "AF_UNIX")
"""Whether Unix sockets are supported.

AF_UNIX is not supported on Windows:
https://github.com/python/cpython/issues/77589

Windows has supported Unix sockets since ~2017, but support in Python is
missing as of 2025.
"""
