# ruff: noqa: UP007  # Avoid using `X | Y` for union fields, as this can cause issues with pydantic < 2.6

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from pydantic import Field
from typing_extensions import Unpack

from wandb._pydantic import Base, GQLId, model_validator

from ._generated import TriggerFields, UserFields
from .actions import InputAction, SavedAction
from .events import InputEvent, SavedEvent
from .scopes import InputScope, SavedScope

if TYPE_CHECKING:
    from wandb import Api

    from ._utils import AutomationParams


# ------------------------------------------------------------------------------
# Saved types: for parsing response data from saved automations
class Automation(TriggerFields):
    """A local instance of a saved W&B automation."""

    id: GQLId

    created_by: UserFields = Field(repr=False, frozen=True, alias="createdBy")
    created_at: datetime = Field(repr=False, frozen=True, alias="createdAt")
    updated_at: Optional[datetime] = Field(repr=False, frozen=True, alias="updatedAt")

    name: str
    description: Optional[str]

    event: SavedEvent
    scope: SavedScope = Field(discriminator="typename__")

    action: SavedAction = Field(discriminator="typename__", alias="triggeredAction")

    enabled: bool

    def save(
        self, api: Api | None = None, **updates: Unpack[AutomationParams]
    ) -> Automation:
        """Save this existing automation to the server, applying any local changes.

        Args:
            api: The API instance to use.  If not provided, the default API instance is used.
            updates:
                Any final updates to apply to the automation before
                saving it.  These override previously-set values, if any.

        Returns:
            The updated automation.
        """
        from wandb import Api

        return (api or Api()).update_automation(self, **updates)

    def delete(self, api: Api | None = None) -> bool:
        """Delete this automation from the server.

        Args:
            api: The API instance to use.  If not provided, the default API instance is used.
        """
        from wandb import Api

        return (api or Api()).delete_automation(self)


class NewAutomation(Base):
    """An automation which can hold any of the fields of a NewAutomation, but may not be complete yet."""

    name: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True

    event: Optional[InputEvent] = None
    scope: Optional[InputScope] = None

    action: Optional[InputAction] = Field(discriminator="action_type", default=None)

    @model_validator(mode="before")
    @classmethod
    def _set_scope_from_event(cls, v: Any) -> Any:
        # If scope wasn't set but the event was, assign its scope to the automation
        # handle either dict or object inputs
        if isinstance(v, dict):
            if (not v.get("scope")) and (event := v.get("event")):
                v["scope"] = event["scope"] if isinstance(event, dict) else event.scope

        elif (not v.scope) and v.event:
            v.scope = v.event.scope

        return v

    def save(
        self, api: Api | None = None, **updates: Unpack[AutomationParams]
    ) -> Automation:
        """Create this automation by saving it to the server.

        Args:
            api: The API instance to use.  If not provided, the default API instance is used.
            updates:
                Any final updates to apply to the automation before
                saving it.  These override previously-set values, if any.

        Returns:
            The created automation.
        """
        from wandb import Api

        return (api or Api()).create_automation(self, **updates)


class PreparedAutomation(NewAutomation):
    """A fully defined automation, ready to be sent to the server to create or update it."""

    name: str
    description: Optional[str] = None
    enabled: bool = True

    event: InputEvent
    scope: InputScope

    action: InputAction
