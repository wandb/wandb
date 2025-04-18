from __future__ import annotations

import secrets
from base64 import b64encode
from functools import lru_cache
from typing import TYPE_CHECKING, Union

from hypothesis import settings
from pytest import FixtureRequest, fixture, skip, xfail
from pytest_mock import MockerFixture
from typing_extensions import TypeAlias
from wandb.apis.public import ArtifactCollection, Project

if TYPE_CHECKING:
    from wandb.automations import (
        ActionType,
        DoNothing,
        DoNotification,
        DoWebhook,
        EventType,
        OnAddArtifactAlias,
        OnCreateArtifact,
        OnLinkArtifact,
        OnRunMetric,
        ScopeType,
    )
    from wandb.automations.actions import InputAction
    from wandb.automations.events import InputEvent

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
    return b64encode(f"{prefix}:{random_index:d}".encode()).decode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@fixture
def integration_id() -> str:
    """Generate a random integration ID for use in tests."""
    return make_graphql_id(prefix="Integration")


@fixture(scope="session")
def artifact_collection(session_mocker: MockerFixture) -> ArtifactCollection:
    """A simulated `ArtifactCollection` that could be returned by `wandb.Api`.

    This might be typically fetched via `Api.artifact_collection()`,
    `Api.artifact().collection`, etc.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    mock_collection = session_mocker.Mock(spec=ArtifactCollection)
    mock_collection.configure_mock(
        **{
            "id": make_graphql_id(prefix="ArtifactCollection"),
            "name": "test-collection",
            "type": "dataset",
            "description": "This is a fake artifact collection.",
            "entity": "test-entity",
            "project": "test-project",
            "is_sequence.return_value": False,
        }
    )
    return mock_collection


@fixture(scope="session")
def project(session_mocker: MockerFixture) -> Project:
    """A simulated `Project` that could be returned by `wandb.Api`.

    This might be typically fetched via `Api.project()`, `Api.projects()`, etc.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    mock_project = session_mocker.Mock(spec=Project)

    mock_project.id = make_graphql_id(prefix="Project")
    mock_project.entity = "test-entity"
    mock_project.name = "test-project"

    return mock_project


# Exclude deprecated scope/event/action types from those expected to be exposed for valid behavior
def valid_scopes() -> list[ScopeType]:
    from wandb.automations import ScopeType

    return sorted(ScopeType)


def valid_events() -> list[EventType]:
    from wandb.automations import EventType

    return sorted(set(EventType) - {EventType.UPDATE_ARTIFACT_ALIAS})


def valid_actions() -> list[ActionType]:
    from wandb.automations import ActionType

    return sorted(set(ActionType) - {ActionType.QUEUE_JOB})


# Invalid (event, scope) combinations that should be skipped
@lru_cache(maxsize=None)
def invalid_events_and_scopes() -> set[tuple[EventType, ScopeType]]:
    from wandb.automations import EventType, ScopeType

    return {
        (EventType.CREATE_ARTIFACT, ScopeType.PROJECT),
        (EventType.RUN_METRIC, ScopeType.ARTIFACT_COLLECTION),
    }


@fixture(params=valid_scopes(), ids=lambda x: x.value)
def scope_type(request: FixtureRequest) -> ScopeType:
    """An automation scope type."""
    return request.param


@fixture(params=valid_events(), ids=lambda x: x.value)
def event_type(request: FixtureRequest, scope_type: ScopeType) -> EventType:
    """An automation event type."""
    from wandb.automations import EventType

    event_type = request.param

    if (event_type, scope_type) in invalid_events_and_scopes():
        skip(f"Event {event_type.value!r} doesn't support scope {scope_type.value!r}")

    if event_type is EventType.RUN_METRIC_CHANGE:
        xfail(f"Event {event_type.value!r} is not yet supported in the SDK")

    return event_type


@fixture(params=valid_actions(), ids=lambda x: x.value)
def action_type(request: type[FixtureRequest]) -> ActionType:
    """An automation action type."""
    return request.param


# ------------------------------------------------------------------------------
# Scopes
@fixture
def scope(request: FixtureRequest, scope_type: ScopeType) -> ScopableWandbType:
    """A (mocked) wandb object to use as the scope for an automation."""
    from wandb.automations import ScopeType

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
    from wandb.automations import OnCreateArtifact

    return OnCreateArtifact(
        scope=scope,
    )


@fixture
def on_add_artifact_alias(scope: ScopableWandbType) -> OnAddArtifactAlias:
    from wandb.automations import ArtifactEvent, OnAddArtifactAlias

    return OnAddArtifactAlias(
        scope=scope,
        filter=ArtifactEvent.alias.matches_regex("^prod-.*"),
    )


@fixture
def on_link_artifact(scope: ScopableWandbType) -> OnLinkArtifact:
    from wandb.automations import ArtifactEvent, OnLinkArtifact

    return OnLinkArtifact(
        scope=scope,
        filter=ArtifactEvent.alias.matches_regex("^prod-.*"),
    )


@fixture
def on_run_metric(scope: ScopableWandbType) -> OnRunMetric:
    from wandb.automations import OnRunMetric, RunEvent

    return OnRunMetric(
        scope=scope,
        filter=RunEvent.metric("my-metric").average(window=5).gt(123.45),
    )


@fixture
def event(request: FixtureRequest, event_type: EventType) -> InputEvent:
    """An event object for defining a **new** automation."""
    from wandb.automations import EventType

    event2fixture: dict[EventType, str] = {
        EventType.CREATE_ARTIFACT: on_create_artifact.__name__,
        EventType.ADD_ARTIFACT_ALIAS: on_add_artifact_alias.__name__,
        EventType.LINK_MODEL: on_link_artifact.__name__,
        EventType.RUN_METRIC: on_run_metric.__name__,
    }
    return request.getfixturevalue(event2fixture[event_type])


# ------------------------------------------------------------------------------
# Actions
@fixture
def do_notification(integration_id: str) -> DoNotification:
    from wandb.automations import DoNotification

    return DoNotification(
        integration_id=integration_id,
        title="Test title",
        text="Test message content",
        level="INFO",
    )


@fixture
def do_webhook(integration_id: str) -> DoWebhook:
    from wandb.automations import DoWebhook

    return DoWebhook(
        integration_id=integration_id,
        request_payload={"my-key": "my-value"},
    )


@fixture
def do_nothing() -> DoNothing:
    from wandb.automations import DoNothing

    return DoNothing()


@fixture
def action(request: FixtureRequest, action_type: ActionType) -> InputAction:
    """An action object for defining a **new** automation."""
    from wandb.automations import ActionType

    action2fixture: dict[ActionType, str] = {
        ActionType.NOTIFICATION: do_notification.__name__,
        ActionType.GENERIC_WEBHOOK: do_webhook.__name__,
        ActionType.NO_OP: do_nothing.__name__,
    }
    return request.getfixturevalue(action2fixture[action_type])
