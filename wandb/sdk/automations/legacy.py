from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import Field, Json, TypeAdapter, field_validator, model_validator
from typing_extensions import Self, assert_never

from wandb.sdk.automations._typing import Base64Id, IntId, UserId
from wandb.sdk.automations.base import Base


class ScopeType(StrEnum):
    """Legacy names of scope types for defined automations."""

    ARTIFACT_COLLECTION = "ARTIFACT_COLLECTION"
    PROJECT = "PROJECT"
    ENTITY = "ENTITY"


class EventType(StrEnum):
    """Legacy names for event types that can trigger automations."""

    ADD_ARTIFACT_ALIAS = "ADD_ARTIFACT_ALIAS"
    LINK_MODEL = "LINK_MODEL"
    CREATE_ARTIFACT = "CREATE_ARTIFACT"
    UPDATE_ARTIFACT_ALIAS = "UPDATE_ARTIFACT_ALIAS"


class EventConfig(Base):
    triggering_event_type: EventType
    payload: EventConfigPayload


class EventConfigPayload(Base):
    filter: Json  # TODO: Parse into MongoDB filters
    # filter: QueryExpression


class ActionType(StrEnum):
    GENERIC_WEBHOOK = "GENERIC_WEBHOOK"
    QUEUE_JOB = "QUEUE_JOB"
    NOTIFICATION = "NOTIFICATION"


# # ActionTypeT = TypeVar("ActionTypeT", bound=ActionType)
# ActionTypeT: TypeAlias = ActionType
# PayloadT = TypeVar("PayloadT", bound=Base)
#
#
# class _Action(Base, Generic[ActionTypeT, PayloadT]):
#     triggered_action_type: ActionTypeT
#     payload: PayloadT


class WebhookAction(Base):
    triggered_action_type: Literal[ActionType.GENERIC_WEBHOOK]
    payload: WebhookPayload


class QueueJobAction(Base):
    triggered_action_type: Literal[ActionType.QUEUE_JOB]
    payload: QueueJobPayload


class NotificationAction(Base):
    triggered_action_type: Literal[ActionType.NOTIFICATION]
    payload: NotificationPayload


class WebhookPayload(Base):
    integration_id: Base64Id
    request_payload: Json


class QueueJobPayload(Base):
    queue_id: Base64Id | None = None
    template: Json  # TODO: Figure out where to import interface/protocol/classes to constrain this


class NotificationPayload(Base):
    title: str
    message: str
    severity: int
    integration_id: Base64Id


ActionConfig = Annotated[
    Union[WebhookAction, QueueJobAction, NotificationAction],
    Field(discriminator="triggered_action_type"),
]


class LegacyAutomation(Base):
    """Legacy schema for saved automations that follows the current `user_triggers` table schema as of Aug 2024."""

    id: IntId

    created_at: datetime
    created_by: UserId
    updated_at: datetime | None = None

    name: str
    description: str | None = None

    enabled: bool

    # Defines triggering EVENT
    triggering_condition_type: Literal["FILTER_TRIGGER"]
    triggering_condition_config: Json[EventConfig]

    scope_type: ScopeType
    scope_id: IntId
    scope_entity_id: IntId | None = None
    scope_project_id: IntId | None = None
    scope_artifact_collection_id: IntId | None = None

    # Defines triggering ACTION
    triggered_action_config: Json[ActionConfig]
    target_queue_id: IntId | None = None
    webhook_id: Base64Id | None = None

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _validate_dt(cls, v: Any) -> Any:
        if isinstance(v, str):
            return datetime.strptime(v, "%Y-%m-%d %H:%M:%S %Z")
        return v

    @model_validator(mode="after")
    def _check_consistent_scope(self) -> Self:
        # Check scope types/ids are consistent
        scope_id = self.scope_id

        scope_artifact_collection_id = self.scope_artifact_collection_id
        scope_project_id = self.scope_project_id
        scope_entity_id = self.scope_entity_id

        match self.scope_type:
            case ScopeType.ARTIFACT_COLLECTION:
                valid_ids = (
                    scope_artifact_collection_id == scope_id
                    and scope_project_id is None
                    and scope_entity_id is None
                )
            case ScopeType.PROJECT:
                valid_ids = (
                    scope_artifact_collection_id is None
                    and scope_project_id == scope_id
                    and scope_entity_id is None
                )
            case ScopeType.ENTITY:
                valid_ids = (
                    scope_artifact_collection_id is None
                    and scope_project_id is None
                    and scope_entity_id == scope_id
                )
            case _ as unknown_scope:
                assert_never(unknown_scope)

        if not valid_ids:
            raise ValueError(f"Invalid IDs for scope {self.scope_type !r}")

        return self


LegacyAutomationAdapter = TypeAdapter(LegacyAutomation)
