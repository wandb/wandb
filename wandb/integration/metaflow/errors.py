import wandb


class MissingDependencyError(Exception):
    """An optional dependency is missing."""

    def __init__(self, *args: object, warning: str) -> None:
        super().__init__(*args)
        self._wb_warning = warning

    def warn(self) -> None:
        """Print a warning for the problem."""
        wandb.termwarn(self._wb_warning)
