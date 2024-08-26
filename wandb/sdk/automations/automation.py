from datetime import datetime

from wandb.sdk.automations._typing import IntId
from wandb.sdk.automations.base import Base


class ActionInfo:
    user_id: IntId
    at: datetime


class Automation(Base):
    id: IntId
    name: str
    description: str | None = None
    enabled: bool

    created: ActionInfo
    updated: ActionInfo
    deleted: ActionInfo

    event: Event
    action: Action
