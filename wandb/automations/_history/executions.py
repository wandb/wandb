from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from wandb._pydantic import GQLId

from .._generated import TriggerExecutionFields, TriggerExecutionState
from .._generated.fragments import (
    TriggerExecutionFieldsAction,
    TriggerExecutionFieldsEvent,
    TriggerExecutionFieldsResult,
)
from ..scopes import AutomationScope


class ExecutedAutomation(TriggerExecutionFields):
    """A local instance of an executed automation."""

    id: GQLId

    automation_id: Optional[GQLId] = Field(alias="automationID")
    """The ID of the Automation that was executed."""

    automation_name: str = Field(alias="automationName")
    """The name of the executed automation when it was triggered.

    Note: This may be different than the current name of the automation if the
    name has been edited since this execution occurred.
    """

    triggered_at: datetime = Field(alias="triggeredAt")
    """The timestamp when this execution was triggered."""

    state: TriggerExecutionState
    """The current state of this executed automation."""

    scope: Optional[AutomationScope]
    event: Optional[TriggerExecutionFieldsEvent]
    action: Optional[TriggerExecutionFieldsAction]
    result: Optional[TriggerExecutionFieldsResult]
