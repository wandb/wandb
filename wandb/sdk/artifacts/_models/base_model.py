from __future__ import annotations

from abc import ABC

from pydantic import ConfigDict

from wandb._pydantic import JsonableModel


# Abstract base class with a common default configuration that's shared by all
# pydantic classes in artifacts code (excluding GraphQL-generated types).
class ArtifactsBase(JsonableModel, ABC):
    # See: https://docs.pydantic.dev/latest/api/config/#pydantic.config.ConfigDict
    model_config = ConfigDict(
        # Most likely, some fields won't be pydantic types
        arbitrary_types_allowed=True,
        # Assume instances of the same class have already been validated to save time,
        # but validate subclasses in case they override the default behavior.
        revalidate_instances="subclass-instances",
    )
