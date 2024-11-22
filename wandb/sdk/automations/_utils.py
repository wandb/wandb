from __future__ import annotations

import sys
from contextlib import suppress
from typing import TYPE_CHECKING, Any, TypeVar, cast

from pydantic import Json, ValidationError, WrapValidator
from pydantic_core import to_json
from pydantic_core.core_schema import ValidatorFunctionWrapHandler

from wandb.sdk.automations._generated.enums import TriggeredActionType, TriggerScopeType
from wandb.sdk.automations._generated.input_types import (
    CreateFilterTriggerInput,
    TriggeredActionConfig,
)

if TYPE_CHECKING:
    from wandb.sdk.automations.automations import ActionInput, NewAutomation

if sys.version_info >= (3, 12):
    from typing import Annotated
else:
    from typing_extensions import Annotated

T = TypeVar("T")


def jsonify(obj: T) -> Json[T]:
    """Return the expected JSON serialization of the given object."""
    json_bytes = to_json(obj, by_alias=True, round_trip=True, bytes_mode="utf8")
    return cast(Json[T], json_bytes.decode("utf8"))


SCOPE_TYPE_MAP: dict[str, TriggerScopeType] = {
    "Project": TriggerScopeType.PROJECT,
    "ArtifactCollection": TriggerScopeType.ARTIFACT_COLLECTION,
    "ArtifactPortfolio": TriggerScopeType.ARTIFACT_COLLECTION,
    "ArtifactSequence": TriggerScopeType.ARTIFACT_COLLECTION,
}
"""Mapping of `__typename`s to automation scope types."""

ACTION_TYPE_MAP: dict[str, TriggeredActionType] = {
    "QueueJobTriggeredAction": TriggeredActionType.QUEUE_JOB,
    "NotificationTriggeredAction": TriggeredActionType.NOTIFICATION,
    "GenericWebhookTriggeredAction": TriggeredActionType.GENERIC_WEBHOOK,
}
"""Mapping of `__typename`s to automation action types."""


def validate_jsonified(v: Any, handler: ValidatorFunctionWrapHandler) -> Any:
    """Wraps default Json[...] field validator to allow instantiation with an already-decoded value."""
    try:
        return handler(v)
    except ValidationError as e:
        # Try revalidating after properly jsonifying the value
        # ... but if it fails, raise the original error.
        with suppress(ValidationError):
            return handler(jsonify(v))
        raise e


def prepare_action_input(obj: ActionInput) -> TriggeredActionConfig:
    """Return a `TriggeredActionConfig` as required in the input schema of CreateFilterTriggerInput."""
    from wandb.sdk.automations.actions import DoLaunchJob, DoNotification, DoWebhook

    if isinstance(obj, DoLaunchJob):
        key = "queue_job_action_input"
    elif isinstance(obj, DoNotification):
        key = "notification_action_input"
    elif isinstance(obj, DoWebhook):
        key = "generic_webhook_action_input"
    else:
        raise TypeError(f"Unsupported action type {type(obj).__qualname__!r}: {obj!r}")

    return TriggeredActionConfig.model_validate({key: obj.model_dump()})


def prepare_create_automation_input(obj: NewAutomation) -> CreateFilterTriggerInput:
    return CreateFilterTriggerInput(
        name=obj.name,
        description=obj.description,
        enabled=obj.enabled,
        client_mutation_id=obj.client_mutation_id,
        # ------------------------------------------------------------------------------
        scope_type=SCOPE_TYPE_MAP[obj.scope.typename__],
        scope_id=obj.scope.id,
        # ------------------------------------------------------------------------------
        triggering_event_type=obj.event.event_type,
        event_filter=jsonify(obj.event.filter),
        # ------------------------------------------------------------------------------
        triggered_action_type=obj.action.action_type,
        triggered_action_config=prepare_action_input(obj.action),
    )


JsonT = TypeVar("JsonT", bound=Json[Any])
SerializedToJson = Annotated[
    Json[T],
    # Lenient on instantiation/validation, as incoming data
    # may or may not be JSON-serialized
    WrapValidator(validate_jsonified),
]
