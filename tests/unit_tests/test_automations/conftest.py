from __future__ import annotations

import base64
import secrets
from collections import defaultdict
from unittest.mock import Mock

from hypothesis import settings
from pytest import FixtureRequest, fixture, skip
from pytest_mock import MockerFixture
from wandb.apis.public import ArtifactCollection, Project
from wandb.sdk.automations.actions import (
    ActionType,
    DoNothing,
    DoNotification,
    DoWebhook,
)
from wandb.sdk.automations.events import (
    ArtifactEvent,
    EventType,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunEvent,
)
from wandb.sdk.automations.scopes import ScopeType

# default Hypothesis settings
settings.register_profile(
    "default",
    max_examples=100,
)
settings.load_profile("default")


# ----------------------------------------------------------------------------
def random_index() -> int:
    """Generate a random integer ID for use in tests."""
    return secrets.randbelow(1_000_000)


def random_graphql_id(prefix: str) -> str:
    """Generate the string "ID" value for a wandb object, enforcing its expected encoding in e.g. a GraphQL response.

    When returned in a GraphQL response, ID values are base64-encoded strings of
    - a named prefix
    - an integer ID

    The original, decoded IDs would have representations such as, e.g.:
    - "Integration:123"
    - "ArtifactCollection:101"
    - etc.
    """
    return base64.b64encode(f"{prefix}:{random_index():d}".encode()).decode()


@fixture
def integration_id() -> str:
    """Generate a random integration ID for use in tests."""
    return random_graphql_id("Integration")


@fixture(scope="session")
def mock_client(session_mocker: MockerFixture) -> Mock:
    """A no-op mock client intended only to help instantiate "scope" objects for unit tests."""
    from wandb.apis.public import RetryingClient

    return session_mocker.Mock(spec=RetryingClient)


@fixture(scope="session")
def artifact_collection(
    session_mocker: MockerFixture, mock_client: Mock
) -> ArtifactCollection:
    """A simulated `ArtifactCollection` that could be returned by `wandb.Api`.

    This might be typically fetched via `Api.artifact_collection()`,
    `Api.artifact().collection`, etc.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    # ArtifactCollection.load() is called on instantiation, so patch it to avoid a live API call
    session_mocker.patch.object(ArtifactCollection, "load")

    mock_attrs = {
        "id": random_graphql_id("ArtifactCollection"),
        "aliases": {"edges": []},
        "tags": {"edges": []},
        "description": "This is a fake artifact collection.",
    }
    return ArtifactCollection(
        client=mock_client,
        entity="test-entity",
        project="test-project",
        name="test-collection",
        type="dataset",
        attrs=mock_attrs,
    )


@fixture(scope="session")
def project(mock_client: Mock) -> Project:
    """A simulated `Project` that could be returned by `wandb.Api`.

    This might be typically fetched via `Api.project()`, `Api.projects()`, etc.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    mock_attrs = {
        "id": random_graphql_id("Project"),
    }
    return Project(
        client=mock_client,
        entity="test-entity",
        project="test-project",
        attrs=mock_attrs,
    )


# Deprecated events/actions that will not be exposed in the API for programmatic creation
DEPRECATED_EVENT_TYPES = {EventType.UPDATE_ARTIFACT_ALIAS}
DEPRECATED_ACTION_TYPES = {ActionType.QUEUE_JOB}

VALID_SCOPE_TYPES = set(ScopeType)
VALID_EVENT_TYPES = set(EventType) - DEPRECATED_EVENT_TYPES
VALID_ACTION_TYPES = set(ActionType) - DEPRECATED_ACTION_TYPES

# Invalid scope types, if any, for each event type
INVALID_SCOPES_BY_EVENT: defaultdict[EventType, set[ScopeType]] = defaultdict(
    set,
    {
        EventType.LINK_MODEL: {ScopeType.PROJECT},
        EventType.RUN_METRIC: {ScopeType.ARTIFACT_COLLECTION},
    },
)


@fixture(params=sorted(VALID_SCOPE_TYPES), ids=lambda x: x.value)
def scope_type(request: FixtureRequest) -> ScopeType:
    """An automation scope type."""
    return request.param


@fixture(params=sorted(VALID_EVENT_TYPES), ids=lambda x: x.value)
def event_type(request: FixtureRequest, scope_type: ScopeType) -> EventType:
    """An automation event type."""
    event_type = request.param
    if scope_type in INVALID_SCOPES_BY_EVENT[event_type]:
        skip(
            f"Event type {event_type.value!r} doesn't support scope type {scope_type.value!r}"
        )
    return event_type


@fixture(params=sorted(VALID_ACTION_TYPES))
def action_type(request: type[FixtureRequest]) -> ActionType:
    """An automation action type."""
    return request.param


# ------------------------------------------------------------------------------
# Scopes
SCOPE2FIXTURENAME: dict[ScopeType, str] = {
    ScopeType.ARTIFACT_COLLECTION: artifact_collection.__name__,
    ScopeType.PROJECT: project.__name__,
}


@fixture
def scope(
    request: FixtureRequest, scope_type: ScopeType
) -> ArtifactCollection | Project:
    """A (mocked) automation scope object."""
    return request.getfixturevalue(SCOPE2FIXTURENAME[scope_type])


# ------------------------------------------------------------------------------
# Events
@fixture
def on_create_artifact(scope: ArtifactCollection | Project) -> OnCreateArtifact:
    """An event object for defining a **new** automation."""
    return OnCreateArtifact(
        scope=scope,
    )


@fixture
def on_add_artifact_alias(scope: ArtifactCollection | Project) -> OnAddArtifactAlias:
    return OnAddArtifactAlias(
        scope=scope,
        filter=ArtifactEvent.alias.matches_regex("^prod-.*"),
    )


@fixture
def on_link_artifact(scope: ArtifactCollection | Project) -> OnLinkArtifact:
    return OnLinkArtifact(
        scope=scope,
        filter=ArtifactEvent.alias.matches_regex("^prod-.*"),
    )


@fixture
def on_run_metric(scope: ArtifactCollection | Project) -> OnRunMetric:
    return OnRunMetric(
        scope=scope,
        filter=RunEvent.metric("my-metric").average(window=5).gt(123.45),
    )


EVENT2FIXTURENAME: dict[EventType, str] = {
    EventType.CREATE_ARTIFACT: on_create_artifact.__name__,
    EventType.ADD_ARTIFACT_ALIAS: on_add_artifact_alias.__name__,
    EventType.LINK_MODEL: on_link_artifact.__name__,
    EventType.RUN_METRIC: on_run_metric.__name__,
}


@fixture
def event(
    request: FixtureRequest,
    event_type: EventType,
) -> OnCreateArtifact | OnLinkArtifact | OnAddArtifactAlias:
    """An event object for defining a **new** automation."""
    return request.getfixturevalue(EVENT2FIXTURENAME[event_type])


# ------------------------------------------------------------------------------
# Actions
@fixture
def do_notification(integration_id: str) -> DoNotification:
    return DoNotification(
        integration_id=integration_id,
        title="Test title",
        text="Test message content",
        level="INFO",
    )


@fixture
def do_webhook(integration_id: str) -> DoWebhook:
    return DoWebhook(
        integration_id=integration_id,
        request_payload={"my-key": "my-value"},
    )


@fixture
def do_nothing() -> DoNothing:
    return DoNothing()


ACTION2FIXTURENAME: dict[ActionType, str] = {
    ActionType.NOTIFICATION: do_notification.__name__,
    ActionType.GENERIC_WEBHOOK: do_webhook.__name__,
    ActionType.NO_OP: do_nothing.__name__,
}


@fixture
def action(
    request: FixtureRequest, action_type: ActionType
) -> DoNotification | DoWebhook | DoNothing:
    """An action object for defining a **new** automation."""
    return request.getfixturevalue(ACTION2FIXTURENAME[action_type])
