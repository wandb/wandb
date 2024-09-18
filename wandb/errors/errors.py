from typing import Optional


class Error(Exception):
    """Base W&B Error."""

    def __init__(self, message, context: Optional[dict] = None) -> None:
        super().__init__(message)
        self.message = message
        # sentry context capture
        if context:
            self.context = context


class CommError(Error):
    """Error communicating with W&B servers."""

    def __init__(self, msg, exc=None) -> None:
        self.exc = exc
        self.message = msg
        super().__init__(self.message)


class AuthenticationError(CommError):
    """Raised when authentication fails."""


class UsageError(Error):
    """Raised when an invalid usage of the SDK API is detected."""


class UnsupportedError(UsageError):
    """Raised when trying to use a feature that is not supported."""


class WandbCoreNotAvailableError(Error):
    """Raised when wandb core is not available."""
