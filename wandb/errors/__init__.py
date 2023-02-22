__all__ = [
    "Error",
    "UsageError",
    "CommError",
    "UnsupportedError",
    "WaitTimeoutError",
]

from typing import Optional


class Error(Exception):
    """Base W&B Error"""

    def __init__(self, message, context: Optional[dict] = None) -> None:
        super().__init__(message)
        self.message = message
        # sentry context capture
        if context:
            self.context = context

    # For python 2 support
    def encode(self, encoding):
        return self.message


class CommError(Error):
    """Error communicating with W&B"""

    def __init__(self, msg, exc=None) -> None:
        super().__init__(msg)
        self.message = msg
        self.exc = exc


class UsageError(Error):
    """API Usage Error"""

    pass


class UnsupportedError(UsageError):
    """Raised when trying to use a feature that is not supported"""


class WaitTimeoutError(Error):
    """Raised when wait() timeout occurs before process is finished"""

    pass
