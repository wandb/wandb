from abc import ABC

from pydantic import BaseModel, ConfigDict


class Base(BaseModel, ABC):
    """Abstract base class for all automation classes/types."""

    model_config = ConfigDict(
        validate_assignment=True,
        extra="forbid",
    )
