from __future__ import annotations

import base64
import secrets
from unittest.mock import Mock

from pytest import FixtureRequest, fixture, skip
from pytest_mock import MockerFixture
from wandb.apis import public
from wandb.sdk.automations.actions import (
    ActionType,
    DoNothing,
    DoNotification,
    DoWebhook,
)
from wandb.sdk.automations.events import (
    EventType,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunEvent,
)
from wandb.sdk.automations.filters._expressions import FilterField
from wandb.sdk.automations.scopes import ScopeType


def random_int_id() -> int:
    """Generate a random integer ID for use in tests."""
    return secrets.randbelow(1_000_000)


def make_graphql_id(prefix: str, idx: int | None = None) -> str:
    """Generate the string "ID" value for a wandb object, enforcing its expected encoding in e.g. a GraphQL response.

    When returned in a GraphQL response, ID values are base64-encoded strings of
    - a named prefix
    - an integer ID

    The original, decoded IDs would have representations such as, e.g.:
    - "Integrations:123"
    - "ArtifactCollection:101"
    - etc.
    """
    idx = random_int_id() if (idx is None) else idx
    return base64.encodebytes(f"{prefix}:{idx:d}".encode()).decode()


@fixture(scope="session")
def mock_client(session_mocker: MockerFixture) -> Mock:
    """A no-op client for instantiating scope types for unit tests that won't make actual API calls."""
    from wandb.apis.public import RetryingClient

    return session_mocker.Mock(spec=RetryingClient)


@fixture(scope="session")
def artifact_collection(
    session_mocker: MockerFixture,
    mock_client: Mock,
) -> public.ArtifactCollection:
    """Simulates an ArtifactCollection that could be returned by the Api.

    This might be typically fetched via `Api.artifact_collection()`, `Api.artifact().collection`, etc.
    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    # ArtifactCollection.load() is called on instantiation, so patch it to avoid a live API call
    session_mocker.patch.object(public.ArtifactCollection, "load")

    mock_attrs = {
        "id": make_graphql_id("ArtifactCollection"),
        "aliases": {"edges": []},
        "tags": {"edges": []},
        "description": "This is a fake artifact collection.",
    }
    return public.ArtifactCollection(
        client=mock_client,
        entity="test-entity",
        project="test-project",
        name="test-collection",
        type="dataset",
        attrs=mock_attrs,
    )


@fixture(scope="session")
def project(mock_client: Mock) -> public.Project:
    """Simulates a Project that could be returned by the Api.

    This might be typically fetched via `Api.project()`, `Api.projects()`, etc.
    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    mock_attrs = {
        "id": make_graphql_id("Project"),
    }
    return public.Project(
        client=mock_client,
        entity="test-entity",
        project="test-project",
        attrs=mock_attrs,
    )


# Deprecated events/actions that will not be exposed in the API for programmatic creation
DEPRECATED_EVENT_TYPES = {EventType.UPDATE_ARTIFACT_ALIAS}
DEPRECATED_ACTION_TYPES = {ActionType.QUEUE_JOB}

# Invalid event+scope pairs that are not allowed by the backend server
UNSUPPORTED_EVENT_AND_SCOPE_TYPES = {
    (EventType.LINK_MODEL, ScopeType.PROJECT),
    (EventType.RUN_METRIC, ScopeType.ARTIFACT_COLLECTION),
}


@fixture(params=sorted(ScopeType))
def scope_type(request: type[FixtureRequest]) -> ScopeType:
    """A fixture that parametrizes over all valid scope types."""
    return request.param


@fixture(params=sorted(set(EventType) - DEPRECATED_EVENT_TYPES))
def event_type(request: type[FixtureRequest], scope_type: ScopeType) -> EventType:
    """A fixture that parametrizes over all valid event types."""
    if (event_type, scope_type) in UNSUPPORTED_EVENT_AND_SCOPE_TYPES:
        skip(f"Not supported: {event_type=} {scope_type=}")
    return request.param


@fixture(params=sorted(set(ActionType) - DEPRECATED_ACTION_TYPES))
def action_type(request: type[FixtureRequest]) -> ActionType:
    """A fixture that parametrizes over all valid action types."""
    return request.param


@fixture
def scope(
    request: type[FixtureRequest], scope_type: ScopeType
) -> public.ArtifactCollection | public.Project:
    """A fixture that parametrizes over (mocked) scope objects."""
    if scope_type is ScopeType.ARTIFACT_COLLECTION:
        return request.getfixturevalue(artifact_collection.__name__)

    if scope_type is ScopeType.PROJECT:
        return request.getfixturevalue(project.__name__)

    raise ValueError(f"Unhandled: {scope_type=}")


@fixture
def event(
    scope: public.ArtifactCollection | public.Project,
    event_type: EventType,
    scope_type: ScopeType,
) -> OnCreateArtifact | OnLinkArtifact | OnAddArtifactAlias:
    """A fixture that parametrizes over event objects for defining new automations."""
    event_and_scope = (event_type, scope_type)

    if event_and_scope in UNSUPPORTED_EVENT_AND_SCOPE_TYPES:
        skip(f"Not supported: {event_and_scope!r}")

    if event_type is EventType.CREATE_ARTIFACT:
        return OnCreateArtifact(scope=scope)

    if event_type is EventType.ADD_ARTIFACT_ALIAS:
        return OnAddArtifactAlias(
            scope=scope,
            filter=FilterField("alias").matches_regex("^prod-.*"),
        )

    if event_type is EventType.LINK_MODEL:
        return OnLinkArtifact(scope=scope)

    if event_type is EventType.RUN_METRIC:
        return OnRunMetric(
            scope=scope,
            filter=RunEvent.metric("my-metric").mean(window=5).gt(123.45),
        )

    raise ValueError(f"Unhandled: {event_type=}")


@fixture
def action(action_type: ActionType) -> DoNotification | DoWebhook:
    """A fixture that parametrizes over action objects for defining new automations."""
    if action_type is ActionType.NOTIFICATION:
        return DoNotification(
            integration_id=make_graphql_id("Integration"),
            title="Test title",
            text="Test message content",
            level="INFO",
        )

    if action_type is ActionType.GENERIC_WEBHOOK:
        return DoWebhook(
            integration_id=make_graphql_id("Integration"),
            request_payload={},
        )

    if action_type is ActionType.QUEUE_JOB:
        skip("Not implemented/supported")

    if action_type is ActionType.NO_OP:
        return DoNothing()

    raise ValueError(f"Unhandled: {action_type=}")
