from typing import List, Optional


class Error(Exception):
    """Base W&B Error"""

    def __init__(self, message) -> None:
        super().__init__(message)
        self.message = message

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


__all__ = [
    "Error",
    "UsageError",
    "CommError",
    "LogError",
    "DockerError",
    "LogMultiprocessError",
    "MultiprocessError",
    "RequireError",
    "ExecutionError",
    "LaunchError",
    "SweepError",
]
