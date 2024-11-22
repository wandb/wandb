from __future__ import annotations

import base64
import secrets
from collections import defaultdict
from unittest.mock import Mock

from hypothesis import HealthCheck, settings
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
    EventType,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunEvent,
)
from wandb.sdk.automations.filters._expressions import FilterField
from wandb.sdk.automations.scopes import ScopeType

# default Hypothesis settings
settings.register_profile(
    "default",
    # wandb_core/no_wandb_core tests may end up running on different executors
    suppress_health_check=[HealthCheck.differing_executors],
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


@fixture(scope="session")
def mock_client(session_mocker: MockerFixture) -> Mock:
    """A no-op client for instantiating scope types for unit tests that won't make actual API calls."""
    from wandb.apis.public import RetryingClient

    return session_mocker.Mock(spec=RetryingClient)


@fixture(scope="session")
def artifact_collection(
    session_mocker: MockerFixture,
    mock_client: Mock,
) -> ArtifactCollection:
    """Simulates an ArtifactCollection that could be returned by the Api.

    This might be typically fetched via `Api.artifact_collection()`, `Api.artifact().collection`, etc.
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
    """Simulates a Project that could be returned by the Api.

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
    """A fixture that parametrizes over all valid scope types."""
    return request.param


@fixture(params=sorted(VALID_EVENT_TYPES), ids=lambda x: x.value)
def event_type(request: FixtureRequest, scope_type: ScopeType) -> EventType:
    """A fixture that parametrizes over all valid event types."""
    event_type = request.param
    if scope_type in INVALID_SCOPES_BY_EVENT[event_type]:
        skip(
            f"Event type {event_type.value!r} doesn't support scope type {scope_type.value!r}"
        )
    return event_type


@fixture(params=sorted(VALID_ACTION_TYPES))
def action_type(request: type[FixtureRequest]) -> ActionType:
    """A fixture that parametrizes over all valid action types."""
    return request.param


@fixture
def scope(
    request: type[FixtureRequest], scope_type: ScopeType
) -> ArtifactCollection | Project:
    """A fixture that parametrizes over (mocked) scope objects."""
    if scope_type is ScopeType.ARTIFACT_COLLECTION:
        return request.getfixturevalue(artifact_collection.__name__)
    if scope_type is ScopeType.PROJECT:
        return request.getfixturevalue(project.__name__)
    raise ValueError(f"Unhandled: {scope_type=}")


@fixture
def event(
    scope: ArtifactCollection | Project,
    event_type: EventType,
) -> OnCreateArtifact | OnLinkArtifact | OnAddArtifactAlias:
    """A fixture that parametrizes over event objects for defining new automations."""
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
            filter=RunEvent.metric("my-metric").average(window=5).gt(123.45),
        )

    raise ValueError(f"Unhandled: {event_type=}")


@fixture
def action(action_type: ActionType) -> DoNotification | DoWebhook | DoNothing:
    """A fixture that parametrizes over action objects for defining new automations."""
    if action_type is ActionType.NOTIFICATION:
        return DoNotification(
            integration_id=random_graphql_id("Integration"),
            title="Test title",
            text="Test message content",
            level="INFO",
        )

    if action_type is ActionType.GENERIC_WEBHOOK:
        return DoWebhook(
            integration_id=random_graphql_id("Integration"),
            request_payload={"my-key": "my-value"},
        )

    if action_type is ActionType.NO_OP:
        return DoNothing()

    raise ValueError(f"Unhandled: {action_type=}")
