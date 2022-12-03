import threading
import typing

# Context variable for setting API settings (api keys, etc.) for internal and public apis thread-locally
class _ThreadLocalApiSettings(threading.local):
    api_key: typing.Optional[str]
    cookies: typing.Optional[typing.Dict]
    headers: typing.Optional[typing.Dict]

    def __init__(self) -> None:
        self.api_key = None
        self.cookies = None
        self.headers = None


_thread_local_api_settings: _ThreadLocalApiSettings = _ThreadLocalApiSettings()
