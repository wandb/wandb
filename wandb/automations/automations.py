from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field

from wandb._pydantic import Connection, GQLId, GQLInput, GQLResult, Typename

from ._generated import TriggerFields
from ._validators import parse_saved_action
from .actions import InputAction, SavedAction
from .events import InputEvent, SavedTriggerEvent
from .scopes import AutomationScope, SavedTriggerScope


# ------------------------------------------------------------------------------
# Saved types: for parsing response data from saved automations while allowing
# local editing.
class Automation(TriggerFields, frozen=False):
    """A local instance of a saved W&B automation that supports editing."""

    id: GQLId

    created_at: Annotated[datetime, Field(repr=False, frozen=True, alias="createdAt")]
    """The date and time when this automation was created."""

    updated_at: Annotated[
        datetime | None, Field(repr=False, frozen=True, alias="updatedAt")
    ] = None
    """The date and time when this automation was last updated, if applicable."""

    name: str
    """The name of this automation."""

    description: str | None
    """An optional description of this automation."""

    enabled: bool
    """Whether this automation is enabled.  Only enabled automations will trigger."""

    event: SavedTriggerEvent
    """The event that will trigger this automation."""

    scope: SavedTriggerScope
    """The scope in which the triggering event must occur."""

    action: Annotated[SavedAction, BeforeValidator(parse_saved_action)]
    """The action that will execute when this automation is triggered."""


class NewAutomation(GQLInput, extra="forbid", validate_default=False):
    """A new automation to be created."""

    name: str | None = None
    """The name of this automation."""

    description: str | None = None
    """An optional description of this automation."""

    enabled: bool | None = None
    """Whether this automation is enabled.  Only enabled automations will trigger."""

    event: InputEvent | None = None
    """The event that will trigger this automation."""

    # Ensure that the event and its scope are always consistent, if the event is set.
    @property
    def scope(self) -> AutomationScope | None:
        """The scope in which the triggering event must occur."""
        return self.event.scope if self.event else None

    @scope.setter
    def scope(self, value: AutomationScope) -> None:
        if self.event is None:
            raise ValueError("Cannot set `scope` for an automation with no `event`")
        self.event.scope = value

    action: InputAction | None = None
    """The action that will execute when this automation is triggered."""


class EntityAutomationsPage(GQLResult):
    """Entity.triggers listing envelope parsed as public `Automation` nodes."""

    scope: EntityAutomationsPageScope | None


class EntityAutomationsPageScope(GQLResult):
    triggers: Connection[Automation]


class ProjectAutomations(GQLResult):
    """Project.triggers listing node parsed as public `Automation` objects."""

    typename__: Typename[Literal["Project"]] = "Project"
    triggers: list[Automation]


class LegacyAutomationsPage(GQLResult):
    """Legacy project-walking listing envelope parsed as public `Automation` nodes."""

    scope: LegacyAutomationsPageScope | None


class LegacyAutomationsPageScope(GQLResult):
    projects: Connection[ProjectAutomations] | None


EntityAutomationsPage.model_rebuild()
EntityAutomationsPageScope.model_rebuild()
ProjectAutomations.model_rebuild()
LegacyAutomationsPage.model_rebuild()
LegacyAutomationsPageScope.model_rebuild()


__all__ = [
    "Automation",
    "NewAutomation",
]
