from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Union
from unittest.mock import Mock

from hypothesis import settings
from pytest import FixtureRequest, fixture, skip
from pytest_mock import MockerFixture
from typing_extensions import TypeAlias
from wandb._strutils import b64encode_ascii
from wandb.apis.public import ArtifactCollection, Project
from wandb.automations import (
    ActionType,
    ArtifactEvent,
    DoNothing,
    EventType,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunEvent,
    ScopeType,
    SendNotification,
    SendWebhook,
)
from wandb.automations._utils import INVALID_INPUT_ACTIONS, INVALID_INPUT_EVENTS
from wandb.automations.actions import InputAction, SavedAction, SavedNoOpAction
from wandb.automations.events import InputEvent, OnRunState, SavedEvent
from wandb.sdk.artifacts._generated import ArtifactCollectionFragment

# default Hypothesis settings
settings.register_profile("default", max_examples=100)
settings.load_profile("default")


ScopableWandbType: TypeAlias = Union[ArtifactCollection, Project]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_graphql_id(prefix: str) -> str:
    """Generate a string GraphQL ID for a wandb object, encoded as would be expected in a GraphQL response.

    ID values returned by the GraphQL API are base64-encoded from strings
    of the form: f"{string_name}:{integer_id}".

    The original, decoded ID strings would have representations such as, e.g.:
    - "Integration:123"
    - "ArtifactCollection:101"
    """
    random_index: int = secrets.randbelow(1_000_000)
    return b64encode_ascii(f"{prefix}:{random_index:d}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@fixture
def integration_id() -> str:
    """Generate a random integration ID for use in tests."""
    return make_graphql_id(prefix="Integration")


@fixture
def automation_id() -> str:
    """Generate a random automation ID for use in tests."""
    return make_graphql_id(prefix="Trigger")


@fixture(scope="session")
def mock_client(session_mocker: MockerFixture) -> Mock:
    """A mocked wandb client to prevent real API calls."""
    from wandb.apis.public import RetryingClient

    return session_mocker.Mock(spec=RetryingClient)


@fixture(scope="session")
def artifact_collection(mock_client: Mock) -> ArtifactCollection:
    """A simulated `ArtifactCollection` that could be returned by `wandb.Api`.

    This might be typically fetched via `Api.artifact_collection()`,
    `Api.artifact().collection`, etc.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    collection_name = "test-collection"
    project_name = "test-project"
    entity_name = "test-entity"
    collection_type = "dataset"
    collection = ArtifactCollection(
        client=mock_client,
        entity=entity_name,
        project=project_name,
        name=collection_name,
        type=collection_type,
        attrs=ArtifactCollectionFragment(
            typename__="ArtifactPortfolio",
            id=make_graphql_id(prefix="ArtifactCollection"),
            name=collection_name,
            project={
                "name": project_name,
                "entity": {
                    "name": entity_name,
                },
            },
            type={"name": collection_type},
            description="This is a fake artifact collection.",
            aliases={"edges": []},
            createdAt="2021-01-01T00:00:00Z",
            updatedAt="2021-01-01T00:00:00Z",
            tags={"edges": []},
        ),
    )

    return collection


@fixture(scope="session")
def project(mock_client: Mock) -> Project:
    """A simulated `Project` that could be returned by `wandb.Api`.

    This might be typically fetched via `Api.project()`, `Api.projects()`, etc.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    return Project(
        client=mock_client,
        entity="test-entity",
        project="test-project",
        attrs={
            "id": make_graphql_id(prefix="Project"),
        },
    )


# Exclude deprecated scope/event/action types from those expected to be exposed for valid behavior
def valid_scopes() -> list[ScopeType]:
    return sorted(set(ScopeType))


def valid_input_events() -> list[EventType]:
    return sorted(set(EventType) - set(INVALID_INPUT_EVENTS))


def valid_input_actions() -> list[ActionType]:
    return sorted(set(ActionType) - set(INVALID_INPUT_ACTIONS))


# Invalid (event, scope) combinations that should be skipped
@lru_cache(maxsize=None)
def invalid_events_and_scopes() -> set[tuple[EventType, ScopeType]]:
    return {
        (EventType.CREATE_ARTIFACT, ScopeType.PROJECT),
        (EventType.RUN_METRIC_THRESHOLD, ScopeType.ARTIFACT_COLLECTION),
        (EventType.RUN_METRIC_CHANGE, ScopeType.ARTIFACT_COLLECTION),
        (EventType.RUN_METRIC_ZSCORE, ScopeType.ARTIFACT_COLLECTION),
        (EventType.RUN_STATE, ScopeType.ARTIFACT_COLLECTION),
    }


@fixture(params=valid_scopes(), ids=lambda x: f"scope={x.value}")
def scope_type(request: FixtureRequest) -> ScopeType:
    """An automation scope type."""
    return request.param


@fixture(params=valid_input_events(), ids=lambda x: f"event={x.value}")
def event_type(request: FixtureRequest, scope_type: ScopeType) -> EventType:
    """An automation event type."""
    event_type = request.param

    if (event_type, scope_type) in invalid_events_and_scopes():
        skip(f"Event {event_type.value!r} doesn't support scope {scope_type.value!r}")

    return event_type


@fixture(params=valid_input_actions(), ids=lambda x: f"action={x.value}")
def action_type(request: FixtureRequest) -> ActionType:
    """An automation action type."""
    return request.param


# ------------------------------------------------------------------------------
# Scopes
@fixture
def scope(request: FixtureRequest, scope_type: ScopeType) -> ScopableWandbType:
    """A (mocked) wandb object to use as the scope for an automation."""
    scope2fixture: dict[ScopeType, str] = {
        ScopeType.ARTIFACT_COLLECTION: artifact_collection.__name__,
        ScopeType.PROJECT: project.__name__,
    }
    return request.getfixturevalue(scope2fixture[scope_type])


# ------------------------------------------------------------------------------
# Events
@fixture
def on_create_artifact(scope: ScopableWandbType) -> OnCreateArtifact:
    """An event object for defining a **new** automation."""

    return OnCreateArtifact(
        scope=scope,
        filter=ArtifactEvent.alias.matches_regex("^prod-.*"),
    )


@fixture
def on_add_artifact_alias(scope: ScopableWandbType) -> OnAddArtifactAlias:
    return OnAddArtifactAlias(
        scope=scope,
        filter=ArtifactEvent.alias.matches_regex("^prod-.*"),
    )


@fixture
def on_link_artifact(scope: ScopableWandbType) -> OnLinkArtifact:
    return OnLinkArtifact(
        scope=scope,
        filter=ArtifactEvent.alias.matches_regex("^prod-.*"),
    )


@fixture
def on_run_metric_threshold(scope: ScopableWandbType) -> OnRunMetric:
    return OnRunMetric(
        scope=scope,
        filter=RunEvent.metric("my-metric").avg(window=5).gt(123.45),
    )


@fixture
def on_run_metric_change(scope: ScopableWandbType) -> OnRunMetric:
    return OnRunMetric(
        scope=scope,
        filter=RunEvent.metric("my-metric").avg(window=5).changes_by(diff=123.45),
    )


@fixture
def on_run_metric_zscore(scope: ScopableWandbType) -> OnRunMetric:
    from wandb.automations._filters.run_metrics import ChangeDir, MetricZScoreFilter

    return OnRunMetric(
        scope=scope,
        filter=MetricZScoreFilter(
            name="my-metric",
            window=5,
            threshold=2.0,
            change_dir=ChangeDir.ANY,
        ),
    )


@fixture
def on_run_state(scope: ScopableWandbType) -> OnRunState:
    return OnRunState(
        scope=scope,
        filter=RunEvent.name.contains("my-run") & (RunEvent.state == "failed"),
    )


@fixture
def input_event(request: FixtureRequest, event_type: EventType) -> InputEvent:
    """An event object for defining a **new** automation."""

    event2fixture: dict[EventType, str] = {
        EventType.CREATE_ARTIFACT: on_create_artifact.__name__,
        EventType.ADD_ARTIFACT_ALIAS: on_add_artifact_alias.__name__,
        EventType.LINK_ARTIFACT: on_link_artifact.__name__,
        EventType.RUN_METRIC_THRESHOLD: on_run_metric_threshold.__name__,
        EventType.RUN_METRIC_CHANGE: on_run_metric_change.__name__,
        EventType.RUN_METRIC_ZSCORE: on_run_metric_zscore.__name__,
        EventType.RUN_STATE: on_run_state.__name__,
    }
    return request.getfixturevalue(event2fixture[event_type])


@fixture
def saved_event() -> SavedEvent:
    # PLACEHOLDER
    return SavedEvent(
        event_type=EventType.LINK_ARTIFACT,
        filter={"filter": {"$or": [{"$and": []}]}},
    )


# ------------------------------------------------------------------------------
# Actions
@fixture
def send_notification(integration_id: str) -> SendNotification:
    return SendNotification(
        integration_id=integration_id,
        title="Test title",
        text="Test message content",
        level="INFO",
    )


@fixture
def send_webhook(integration_id: str) -> SendWebhook:
    return SendWebhook(
        integration_id=integration_id, request_payload={"my-key": "my-value"}
    )


@fixture
def do_nothing() -> DoNothing:
    return DoNothing()


@fixture
def input_action(request: FixtureRequest, action_type: ActionType) -> InputAction:
    """An action object for defining a **new** automation."""
    action2fixture: dict[ActionType, str] = {
        ActionType.NOTIFICATION: send_notification.__name__,
        ActionType.GENERIC_WEBHOOK: send_webhook.__name__,
        ActionType.NO_OP: do_nothing.__name__,
    }
    return request.getfixturevalue(action2fixture[action_type])


@fixture
def saved_action() -> SavedAction:
    # PLACEHOLDER
    return SavedNoOpAction()
