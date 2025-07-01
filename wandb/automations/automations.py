from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field
from typing_extensions import Annotated

from wandb._pydantic import GQLBase, GQLId

from ._generated import TriggerFields
from .actions import InputAction, SavedAction
from .events import InputEvent, SavedEvent
from .scopes import AutomationScope


# ------------------------------------------------------------------------------
# Saved types: for parsing response data from saved automations
class Automation(TriggerFields):
    """A local instance of a saved W&B automation."""

    id: GQLId

    created_at: Annotated[datetime, Field(repr=False, frozen=True, alias="createdAt")]
    """The date and time when this automation was created."""

    updated_at: Annotated[
        Optional[datetime], Field(repr=False, frozen=True, alias="updatedAt")
    ] = None
    """The date and time when this automation was last updated, if applicable."""

    name: str
    """The name of this automation."""

    description: Optional[str]
    """An optional description of this automation."""

    enabled: bool
    """Whether this automation is enabled.  Only enabled automations will trigger."""

    event: SavedEvent
    """The event that will trigger this automation."""

    scope: AutomationScope
    """The scope in which the triggering event must occur."""

    action: SavedAction
    """The action that will execute when this automation is triggered."""


class NewAutomation(GQLBase, extra="forbid", validate_default=False):
    """A new automation to be created."""

    name: Optional[str] = None
    """The name of this automation."""

    description: Optional[str] = None
    """An optional description of this automation."""

    enabled: Optional[bool] = None
    """Whether this automation is enabled.  Only enabled automations will trigger."""

    event: Optional[InputEvent] = None
    """The event that will trigger this automation."""

    # Ensure that the event and its scope are always consistent, if the event is set.
    @property
    def scope(self) -> Optional[AutomationScope]:
        """The scope in which the triggering event must occur."""
        return self.event.scope if self.event else None

    @scope.setter
    def scope(self, value: AutomationScope) -> None:
        if self.event is None:
            raise ValueError("Cannot set `scope` for an automation with no `event`")
        self.event.scope = value

    action: Optional[InputAction] = None
    """The action that will execute when this automation is triggered."""


__all__ = [
    "Automation",
    "NewAutomation",
]
