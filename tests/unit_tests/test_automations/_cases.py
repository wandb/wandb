"""Supported input cases shared by fixtures and explicit contract matrices."""

from functools import cache

from wandb.automations import ActionType, EventType, ScopeType
from wandb.automations._inputs import INVALID_INPUT_ACTIONS, INVALID_INPUT_EVENTS


# Exclude deprecated scope/event/action types from those expected to be exposed for valid behavior
def valid_scopes() -> list[ScopeType]:
    # return sorted(set(ScopeType))  # TODO: restore once ENTITY scope is supported
    return sorted(set(ScopeType) - {ScopeType.ENTITY})


def valid_input_events() -> list[EventType]:
    return sorted(set(EventType) - set(INVALID_INPUT_EVENTS))


def valid_input_actions() -> list[ActionType]:
    return sorted(set(ActionType) - set(INVALID_INPUT_ACTIONS))


# Invalid (event, scope) combinations that should be skipped
@cache
def invalid_events_and_scopes() -> set[tuple[EventType, ScopeType]]:
    return {
        (EventType.CREATE_ARTIFACT, ScopeType.ENTITY),
        (EventType.CREATE_ARTIFACT, ScopeType.PROJECT),
        (EventType.RUN_METRIC_THRESHOLD, ScopeType.ARTIFACT_COLLECTION),
        (EventType.RUN_METRIC_CHANGE, ScopeType.ARTIFACT_COLLECTION),
        (EventType.RUN_METRIC_ZSCORE, ScopeType.ARTIFACT_COLLECTION),
        (EventType.RUN_STATE, ScopeType.ARTIFACT_COLLECTION),
        (EventType.SANDBOX_STATE, ScopeType.ARTIFACT_COLLECTION),
    }
