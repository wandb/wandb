from pydantic import ConfigDict

from wandb._pydantic import JsonableModel


# Base class with default behavior for all non-generated types in Artifacts code.
class ArtifactsBase(JsonableModel):
    # ----------------------------------------------------------------------------
    # See: https://docs.pydantic.dev/latest/api/config/#pydantic.config.ConfigDict
    # ----------------------------------------------------------------------------
    model_config = ConfigDict(
        from_attributes=True,  # Can parse from any object with matching attributes, not just dicts
        validate_assignment=True,  # Revalidate whenever we assign a new value to a field
        arbitrary_types_allowed=True,  # Most likely, some fields won't be pydantic types
        revalidate_instances="subclass-instances",
        use_attribute_docstrings=True,  # Attribute docstrings are also used as Field descriptions
    )
