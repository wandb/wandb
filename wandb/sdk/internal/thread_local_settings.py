import threading
from typing import Dict, Optional


# Context variable for setting API settings (api keys, etc.) for internal and public apis thread-locally
# TODO: move this into actual settings
class _ThreadLocalApiSettings(threading.local):
    api_key: Optional[str]
    cookies: Optional[Dict]
    headers: Optional[Dict]

    def __init__(self) -> None:
        self.api_key = None
        self.cookies = None
        self.headers = None


_thread_local_api_settings: _ThreadLocalApiSettings = _ThreadLocalApiSettings()
