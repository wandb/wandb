from pydantic import ConfigDict

from wandb._pydantic import JsonableModel


# Base class with default behavior for all non-generated types in Artifacts code.
# For model_config options, see: https://docs.pydantic.dev/latest/api/config/#pydantic.config.ConfigDict
class ArtifactsBase(JsonableModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,  # Most likely, some fields won't be pydantic types
        revalidate_instances="subclass-instances",
    )
