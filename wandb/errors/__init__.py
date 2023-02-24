__all__ = [
    "Error",
    "CommError",
    "BackendTimeoutError",
    "BackendPermissionsError",
    "BackendAuthenticationError",
    "BackendAuthorizationError",
    "UsageError",
    "InvalidError",
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
        super().__init__(msg)
        self.message = msg
        self.exc = exc


class BackendError(CommError):
    """Error communicating with W&B backend"""


class BackendTimeoutError(BackendError):
    """Raised when a connection times out"""


class BackendPermissionsError(BackendError):
    """Raised when tries to access a resource that without sufficient permissions"""


class BackendAuthenticationError(BackendError):
    """Raised when fails to provide valid authentication credentials"""


class BackendAuthorizationError(BackendError):
    """Raised when not authorized to access a particular resource"""


class UsageError(Error):
    """Raised when an invalid usage of the SDK API is detected"""

    pass


class InvalidError(UsageError):
    """Raised when an invalid argument is passed to a function"""

    pass


class UnsupportedError(UsageError):
    """Raised when trying to use a feature that is not supported"""

    pass


class DependencyError(UsageError):
    """Raised when there is a missing or invalid dependency"""

    pass


class InternalError(CommError):
    """Raised when an SDK internal error occurs"""

    pass


class WaitTimeoutError(Error):
    """Raised when wait() timeout occurs before process is finished"""

    pass
