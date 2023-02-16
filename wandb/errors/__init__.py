__all__ = [
    "Error",
    "UsageError",
    "CommError",
    "LogError",
    "DockerError",
    "UnsupportedError",
    "RequireError",
    "ExecutionError",
    "LaunchError",
    "SweepError",
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


class TimeoutError(CommError):
    """Raised when a connection times out"""


class PermissionsError(CommError):
    """Raised when tries to access a resource that without sufficient permissions"""


class AuthenticationError(CommError):
    """Raised when fails to provide valid authentication credentials"""


class AuthorizationError(CommError):
    """Raised when not authorized to access a particular resource"""


class RateLimitError(CommError):
    """Raised when there is a rate limit error"""


class UsageError(Error):
    """API Usage Error"""

    pass


class InvalidError(UsageError):
    """Raised when an invalid argument is passed to a function"""

    pass


class UnsupportedError(Error):
    """Raised when fails because of multiprocessing"""

    pass


class InternalError(Error):
    """Raised when an internal error occurs"""

    pass


class RequireError(Error):
    """Raised when wandb.require() fails"""

    pass


class ExecutionError(Error):
    """Generic execution exception"""

    pass


class DockerError(Error):
    """Raised when attempting to execute a docker command"""

    def __init__(
        self,
        command_launched: List[str],
        return_code: int,
        stdout: Optional[bytes] = None,
        stderr: Optional[bytes] = None,
    ) -> None:
        command_launched_str = " ".join(command_launched)
        error_msg = (
            f"The docker command executed was `{command_launched_str}`.\n"
            f"It returned with code {return_code}\n"
        )
        if stdout is not None:
            error_msg += f"The content of stdout is '{stdout.decode()}'\n"
        else:
            error_msg += (
                "The content of stdout can be found above the "
                "stacktrace (it wasn't captured).\n"
            )
        if stderr is not None:
            error_msg += f"The content of stderr is '{stderr.decode()}'\n"
        else:
            error_msg += (
                "The content of stderr can be found above the "
                "stacktrace (it wasn't captured)."
            )
        super().__init__(error_msg)


class LaunchError(Error):
    """Raised when a known error occurs in wandb launch"""

    pass


class SweepError(Error):
    """Raised when a known error occurs with wandb sweeps"""

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
