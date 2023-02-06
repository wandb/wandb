__all__ = [
    "Error",
    "UsageError",
    "CommError",
    "DockerError",
    "UnsupportedError",
    "RequireError",
    "ExecutionError",
    "LaunchError",
    "SweepError",
    "WaitTimeoutError",
    "ContextCancelledError",
    "ServiceStartProcessError",
    "ServiceStartTimeoutError",
    "ServiceStartPortError",
]


from typing import List, Optional


### Errors caused by the Server ###


class Error(Exception):
    """Base W&B Error"""

    def __init__(self, message) -> None:
        super().__init__(message)
        self.message = message


class CommError(Error):
    """Error communicating with W&B"""

    def __init__(self, msg, exc=None) -> None:
        super().__init__(msg)
        self.message = msg
        self.exc = exc


class ServerError(CommError):
    """Raised when the backend returns an error."""

    pass


class ServerTransientError(ServerError):
    """Raised when the backend returns an error that can be retried."""

    pass


class ServerUnavailableError(ServerTransientError):
    """Raised when the backend returns a server unavailable error."""

    pass


class ServerTimeoutError(ServerTransientError):
    """Raised when the backend returns a timeout error."""

    pass


class ServerRateLimitError(ServerTransientError):
    """Raised when the backend returns a rate limit error."""

    pass


class ServerPermanentError(ServerError):
    """Raised when the backend returns an error that cannot be retried."""

    pass


### Errors caused by the Internal SDK logic ###


class InternalError(Error):
    """Raised when an internal error occurs."""

    pass


class UnsupportedError(Error):
    """Raised when fails because of multiprocessing"""

    pass


class Abort(InternalError):
    """Raised when critical errors occur."""

    pass


class RequireError(InternalError):
    """Raised when wandb.require() fails"""

    pass


class MailboxError(InternalError):
    """Generic Mailbox Exception"""

    pass


class ContextCancelledError(MailboxError):
    """Context cancelled Exception"""

    pass


class ServiceError(InternalError):
    """Generic Service Exception"""

    pass


class ServiceStartProcessError(ServiceError):
    """Raised when a known error occurs when launching wandb service"""

    pass


class ServiceStartTimeoutError(ServiceError):
    """Raised when service start times out"""

    pass


class ServiceStartPortError(ServiceError):
    """Raised when service start fails to find a port"""

    pass


### Errors caused by the user ###


class UserError(Error):
    """Raised when a user error occurs."""

    pass


class UsageError(UserError):
    """Raised when a usage error occurs."""

    pass


### Errors requires owner review ###


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
