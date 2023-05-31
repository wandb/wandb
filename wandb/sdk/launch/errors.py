from wandb.errors import Error


class LaunchError(Error):
    """Raised when a known error occurs in wandb launch."""

    pass


class LaunchDockerError(Error):
    """Raised when Docker daemon is not running."""

    pass


class ExecutionError(Error):
    """Generic execution exception."""

    pass
