from datetime import datetime

from wandb.sdk.automations._typing import IntId
from wandb.sdk.automations.base import Base


class UpdateInfo:
    user_id: IntId
    at: datetime


class Event(Base):
    pass


class Action(Base):
    pass


class Automation(Base):
    id: IntId
    name: str
    description: str | None = None
    enabled: bool

    created: UpdateInfo
    updated: UpdateInfo | None = None
    deleted: UpdateInfo | None = None

    event: Event
    action: Action
