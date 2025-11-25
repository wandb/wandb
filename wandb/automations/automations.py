from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from pydantic import Field, PositiveInt
from typing_extensions import Annotated

from wandb._pydantic import GQLId, GQLInput

from ._generated import TriggerFields
from .actions import InputAction, SavedAction
from .events import InputEvent, SavedEvent
from .scopes import AutomationScope

if TYPE_CHECKING:
    from wandb.apis.public.automations import ExecutedAutomations


# ------------------------------------------------------------------------------
# Saved types: for parsing response data from saved automations while allowing
# local editing.
class Automation(TriggerFields, frozen=False):
    """A local instance of a saved W&B automation that supports editing."""

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

    def history(self, per_page: PositiveInt = 50) -> ExecutedAutomations:
        from wandb_gql import gql

        from wandb.apis.public Api, ExecutedAutomations
        from wandb.automations._generated import GET_AUTOMATION_HISTORY_GQL

        # FIXME: there needs to be a default client session (like other python libraries do)
        # that avoids the perf hit of instantiating the entire Api/InternalApi classes.
        return ExecutedAutomations(
            Api().client,
            variables={"id": self.id},
            per_page=per_page,
            _query=gql(GET_AUTOMATION_HISTORY_GQL),
        )


class NewAutomation(GQLInput, extra="forbid", validate_default=False):
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
