"""Functions for declaring wandb.config keys that should be used as template parameters."""

from typing import Callable, Optional


class WandbConfigKeys:
    """A class for declaring wandb.config keys that should be used as template parameters."""

    def __init__(
        self,
        keys: Optional[list[str]] = None,
        include_fn: Optional[Callable[[str], bool]] = None,
        exclude_fn: Optional[Callable[[str], bool]] = None,
    ):
        if sum([bool(keys), bool(include_fn), bool(exclude_fn)]) > 1:
            raise ValueError(
                "Only one of keys, include_fn, or exclude_fn should be provided."
            )

        self.keys = keys
        self.include_fn = include_fn
        self.exclude_fn = exclude_fn
