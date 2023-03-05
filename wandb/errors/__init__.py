__all__ = [
    "Error",
    "CommError",
    "BackendError",
    "UsageError",
    "UnsupportedError",
    "DependencyError",
    "InternalError",
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


class CommError(Error):
    """Error communicating with W&B (legacy error for backwards compatibility)"""

    def __init__(self, msg, exc=None) -> None:
        self.exc = exc
        self.message = msg
        super().__init__(self.message)


class BackendError(CommError):
    """Error communicating with W&B backend"""


class UsageError(Error):
    """Raised when an invalid usage of the SDK API is detected"""


class UnsupportedError(UsageError):
    """Raised when trying to use a feature that is not supported"""


class DependencyError(UsageError):
    """Raised when there is a missing or invalid dependency"""


class InternalError(Error):
    """Raised when an SDK internal error occurs"""


class WaitTimeoutError(Error):
    """Raised when wait() timeout occurs before process is finished"""
