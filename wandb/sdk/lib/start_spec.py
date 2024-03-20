import typing
from dataclasses import dataclass


@dataclass
class StartSpec:
    """Specification for how to fork a run from a previous run."""

    run: str  # run ID to fork from
    value: typing.Union[
        int, float
    ]  # currently, the _step value to fork from. in future, this will be optional
