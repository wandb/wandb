__all__ = [
    "Error",
    "UsageError",
    "CommError",
    "LogError",
    "LogMultiprocessError",
    "MultiprocessError",
    "RequireError",
    "WaitTimeoutError",
    "ContextCancelledError",
]

from typing import List, Optional


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


class LogError(Error):
    """Raised when wandb.log() fails"""

    pass


class LogMultiprocessError(LogError):
    """Raised when wandb.log() fails because of multiprocessing"""

    pass


class MultiprocessError(Error):
    """Raised when fails because of multiprocessing"""

    pass


class RequireError(Error):
    """Raised when wandb.require() fails"""

    pass


class WaitTimeoutError(Error):
    """Raised when wait() timeout occurs before process is finished"""

    pass


class MailboxError(Error):
    """Generic Mailbox Exception"""

    pass


class ContextCancelledError(Error):
    """Context cancelled Exception"""

    pass
