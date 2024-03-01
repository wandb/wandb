"""Functions for declaring wandb.config keys that should be used as template parameters."""

from typing import List, Optional

from wandb.proto import wandb_internal_pb2 as pb


class WandbConfigKeys:
    """A class for declaring wandb.config keys that should be used as template parameters."""

    def __init__(
        self,
        include: Optional[List[str]] = None,
        ignore: Optional[List[str]] = None,
    ):
        if sum([bool(include), bool(ignore)]) > 1:
            raise ValueError(
                "Only one of `include` and `ignore` can be specified, not both."
            )
        self.include = include
        self.ignore = ignore
