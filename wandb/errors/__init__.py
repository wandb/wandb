__all__ = [
    "Error",
    "CommError",
    "TimeoutError",
    "PermissionsError",
    "AuthenticationError",
    "AuthorizationError",
    "UsageError",
    "InvalidError",
    "UnsupportedError",
    "ConfigurationError",
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
    """Error communicating with W&B"""

    def __init__(self, msg, exc=None) -> None:
        super().__init__(msg)
        self.message = msg
        self.exc = exc


class TimeoutError(CommError):
    """Raised when a connection times out"""


class PermissionsError(CommError):
    """Raised when tries to access a resource that without sufficient permissions"""


class AuthenticationError(CommError):
    """Raised when fails to provide valid authentication credentials"""


class AuthorizationError(CommError):
    """Raised when not authorized to access a particular resource"""


class UsageError(Error):
    """Raised when an invalid usage of the API is detected"""

    pass


class InvalidError(UsageError):
    """Raised when an invalid argument is passed to a function"""

    pass


class UnsupportedError(UsageError):
    """Raised when trying to use a feature that is not supported"""

    pass


class ConfigurationError(UsageError):
    """Raised when something is misconfigured"""

    pass


class DependencyError(UsageError):
    """Raised when there is a missing or invalid dependency"""

    pass


class InternalError(Error):
    """Raised when an internal error occurs"""

    pass


class WaitTimeoutError(Error):
    """Raised when wait() timeout occurs before process is finished"""

    pass
