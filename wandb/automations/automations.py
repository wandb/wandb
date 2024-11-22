from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import Field

from wandb._pydantic import Base, GQLId, field_validator

from ._generated import TriggerFields, UserFields
from ._validators import validate_scope
from .actions import InputAction, SavedAction
from .events import InputEvent, SavedFilterEvent
from .scopes import InputScope, SavedScope


# ------------------------------------------------------------------------------
# Saved types: for parsing response data from saved automations
class Automation(TriggerFields):
    """A local instance of a saved W&B automation."""

    id: GQLId

    created_by: UserFields = Field(repr=False, frozen=True)
    created_at: datetime = Field(repr=False, frozen=True)
    updated_at: Optional[datetime] = Field(repr=False, frozen=True)

    name: str
    description: Optional[str]

    scope: SavedScope = Field(discriminator="typename__")
    event: SavedFilterEvent
    action: SavedAction = Field(
        discriminator="typename__",
        alias="triggeredAction",
        # validation_alias="triggered_action",
    )

    enabled: bool

    @field_validator("scope", mode="before")
    def _validate_scope(cls, v: Any) -> Any:
        return validate_scope(v)


class NewAutomation(Base):
    """An automation which can hold any of the fields of a NewAutomation, but may not be complete yet."""

    name: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True

    scope: Optional[InputScope] = Field(discriminator="typename__", default=None)
    event: Optional[InputEvent] = Field(discriminator="event_type", default=None)
    action: Optional[InputAction] = Field(discriminator="action_type", default=None)

    @field_validator("scope", mode="before")
    def _validate_scope(cls, v: Any) -> Any:
        return v if (v is None) else validate_scope(v)


class PreparedAutomation(NewAutomation):
    """A fully defined automation, ready to be sent to the server to create or update it."""

    name: str
    description: Optional[str] = None
    enabled: bool = True

    scope: InputScope = Field(discriminator="typename__")
    event: InputEvent = Field(discriminator="event_type")
    action: InputAction = Field(discriminator="action_type")
