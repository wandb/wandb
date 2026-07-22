from __future__ import annotations

import json
import secrets
from functools import cache
from typing import TypeAlias
from unittest.mock import Mock

from hypothesis import settings
from pytest import FixtureRequest, fixture, skip
from pytest_mock import MockerFixture
from wandb._strutils import b64encode_ascii
from wandb.apis.public import ArtifactCollection, Organization, Project, Registry, Team
from wandb.automations import (
    ActionType,
    ArtifactEvent,
    DoNothing,
    EventType,
    OnAddArtifactAlias,
    OnAddArtifactTag,
    OnAddCollectionTag,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRemoveArtifactTag,
    OnRemoveCollectionTag,
    OnRunMetric,
    OnUnlinkArtifact,
    RunEvent,
    ScopeType,
    SendNotification,
    SendWebhook,
)
from wandb.automations._utils import INVALID_INPUT_ACTIONS, INVALID_INPUT_EVENTS
from wandb.automations.actions import (
    InputAction,
    SavedAction,
    SavedNoOpAction,
    SavedNotificationAction,
    SavedWebhookAction,
)
from wandb.automations.automations import Automation
from wandb.automations.events import InputEvent, OnRunState, SavedEvent
from wandb.sdk.artifacts._generated import ArtifactCollectionFragment, RegistryFragment

# default Hypothesis settings
settings.register_profile("default", max_examples=100)
settings.load_profile("default")


ScopableWandbType: TypeAlias = (
    ArtifactCollection | Project | Registry | Team | Organization
)


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
    from wandb.apis.public.service_api import ServiceApi

    return session_mocker.Mock(spec=ServiceApi)


@fixture(scope="session")
def artifact_collection(mock_client: Mock) -> ArtifactCollection:
    """A simulated `ArtifactCollection` that could be returned by `wandb.Api`.

    This might be typically fetched via `Api.artifact_collection()`,
    `Api.artifact().collection`, etc.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    name = "test-collection"
    project = "test-project"
    entity = "test-entity"
    artifact_type = "dataset"
    return ArtifactCollection(
        service_api=mock_client,
        entity=entity,
        project=project,
        name=name,
        type=artifact_type,
        attrs=ArtifactCollectionFragment(
            typename__="ArtifactPortfolio",
            id=make_graphql_id(prefix="ArtifactCollection"),
            name=name,
            project={
                "name": project,
                "entity": {"name": entity},
            },
            type={"name": artifact_type},
            description="This is a fake artifact collection.",
            aliases={"edges": []},
            createdAt="2021-01-01T00:00:00Z",
            updatedAt="2021-01-01T00:00:00Z",
            tags={"edges": []},
        ),
    )


@fixture(scope="session")
def project(mock_client: Mock) -> Project:
    """A simulated `Project` that could be returned by `wandb.Api`.

    This might be typically fetched via `Api.project()`, `Api.projects()`, etc.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    return Project(
        service_api=mock_client,
        entity="test-entity",
        project="test-project",
        attrs={
            "id": make_graphql_id(prefix="Project"),
        },
    )


@fixture(scope="session")
def registry(mock_client: Mock) -> Registry:
    """A simulated `Registry` that could be returned by `wandb.Api`.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    name = "test-registry"
    organization = "test-organization"
    entity = "test-entity"
    return Registry(
        service_api=mock_client,
        name=name,
        entity=entity,
        organization=organization,
        attrs=RegistryFragment(
            id=make_graphql_id(prefix="Project"),
            name=f"wandb-registry-{name}",
            description="This is a fake registry.",
            created_at="2021-01-01T00:00:00Z",
            updated_at=None,
            access="organization",
            allow_all_artifact_types=True,
            artifact_types={"edges": []},
            entity={"name": entity, "organization": {"name": organization}},
        ),
    )


@fixture(scope="session")
def team(mock_client: Mock) -> Team:
    """A simulated `Team` (team entity) that could be returned by `wandb.Api`.

    Typically fetched via `Api.team()`.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    name = "test-team-entity"
    return Team(
        service_api=mock_client,
        name=name,
        attrs={
            "__typename": "Entity",
            "id": make_graphql_id(prefix="Entity"),
            "name": name,
            "entityType": "team",
        },
    )


@fixture(scope="session")
def org(mock_client: Mock) -> Organization:
    """A simulated `Organization` with a mock org entity.

    Typically fetched via `Api.organization()`.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """
    name = "test-org"
    return Organization(
        mock_client,
        **{
            "id": make_graphql_id(prefix="Organization"),
            "name": name,
            "orgEntity": {
                "__typename": "Entity",
                "id": make_graphql_id(prefix="Entity"),
                "name": f"{name}-entity",
                "entityType": "organization",
            },
        },
    )


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
        ScopeType.ENTITY: team.__name__,
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
def on_add_artifact_tag(scope: ScopableWandbType) -> OnAddArtifactTag:
    return OnAddArtifactTag(
        scope=scope,
        filter=ArtifactEvent.tag.matches_regex("^prod-.*"),
    )


@fixture
def on_remove_artifact_tag(scope: ScopableWandbType) -> OnRemoveArtifactTag:
    return OnRemoveArtifactTag(
        scope=scope,
        filter=ArtifactEvent.tag.matches_regex("^prod-.*"),
    )


@fixture
def on_add_collection_tag(scope: ScopableWandbType) -> OnAddCollectionTag:
    return OnAddCollectionTag(
        scope=scope,
        filter=ArtifactEvent.tag.matches_regex("^prod-.*"),
    )


@fixture
def on_remove_collection_tag(scope: ScopableWandbType) -> OnRemoveCollectionTag:
    return OnRemoveCollectionTag(
        scope=scope,
        filter=ArtifactEvent.tag.matches_regex("^prod-.*"),
    )


@fixture
def on_link_artifact(scope: ScopableWandbType) -> OnLinkArtifact:
    return OnLinkArtifact(
        scope=scope,
        filter=ArtifactEvent.alias.matches_regex("^prod-.*"),
    )


@fixture
def on_unlink_artifact(scope: ScopableWandbType) -> OnUnlinkArtifact:
    return OnUnlinkArtifact(scope=scope)


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
    from wandb.automations._run_metric_filters import ChangeDir, MetricZScoreFilter

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
        EventType.ADD_ARTIFACT_TAG: on_add_artifact_tag.__name__,
        EventType.REMOVE_ARTIFACT_TAG: on_remove_artifact_tag.__name__,
        EventType.ADD_COLLECTION_TAG: on_add_collection_tag.__name__,
        EventType.REMOVE_COLLECTION_TAG: on_remove_collection_tag.__name__,
        EventType.LINK_ARTIFACT: on_link_artifact.__name__,
        EventType.UNLINK_ARTIFACT: on_unlink_artifact.__name__,
        EventType.RUN_METRIC_THRESHOLD: on_run_metric_threshold.__name__,
        EventType.RUN_METRIC_CHANGE: on_run_metric_change.__name__,
        EventType.RUN_METRIC_ZSCORE: on_run_metric_zscore.__name__,
        EventType.RUN_STATE: on_run_state.__name__,
    }
    return request.getfixturevalue(event2fixture[event_type])


_MUTATION_EVENT_TYPES = (
    EventType.ADD_ARTIFACT_ALIAS,
    EventType.ADD_ARTIFACT_TAG,
    EventType.ADD_COLLECTION_TAG,
    EventType.LINK_ARTIFACT,
    EventType.REMOVE_ARTIFACT_TAG,
    EventType.REMOVE_COLLECTION_TAG,
    EventType.CREATE_ARTIFACT,
    EventType.UNLINK_ARTIFACT,
)


@fixture(
    params=_MUTATION_EVENT_TYPES,
    ids=lambda x: f"mutation_event={x.value}",
)
def mutation_event_type(request: FixtureRequest) -> EventType:
    """A mutation-based event type."""
    return request.param


@fixture
def saved_event(mutation_event_type: EventType) -> SavedEvent:
    """A realistic SavedEvent with a non-empty wrapped filter."""
    wrapped_filter = {"filter": {"$or": [{"$and": [{"alias": {"$eq": "latest"}}]}]}}
    return SavedEvent(
        event_type=mutation_event_type,
        filter=json.dumps(wrapped_filter),
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


@fixture(params=valid_input_actions())
def saved_action(request: FixtureRequest) -> SavedAction:
    match action_type := request.param:
        case ActionType.NO_OP:
            return SavedNoOpAction()
        case ActionType.NOTIFICATION:
            return SavedNotificationAction(
                integration={"id": "PLACEHOLDER"},
                title=None,
                message=None,
                severity=None,
            )
        case ActionType.GENERIC_WEBHOOK:
            return SavedWebhookAction(
                integration={"id": "PLACEHOLDER"},
                request_payload=None,
            )
        case _:
            raise ValueError(f"Unsupported saved action type: {action_type!r}")


@fixture
def saved_automation(
    automation_id: str,
    saved_event: SavedEvent,
    saved_action: SavedAction,
    artifact_collection: ArtifactCollection,
) -> Automation:
    """An Automation object mimicking what the server returns, for unit-testing prepare_to_update()."""
    return Automation(
        id=automation_id,
        created_at="2024-01-01T00:00:00Z",
        updated_at=None,
        name="test-automation",
        description="test description",
        enabled=True,
        scope=artifact_collection,
        event=saved_event,
        action=saved_action,
    )


RUN_EVENT_TYPES = (
    EventType.RUN_METRIC_THRESHOLD,
    EventType.RUN_STATE,
)


@fixture(
    params=RUN_EVENT_TYPES,
    ids=lambda x: f"run_event={x.value}",
)
def run_event_type(request: FixtureRequest) -> EventType:
    """A run-based event type."""
    return request.param


@fixture
def run_event_filter_json(run_event_type: EventType) -> str:
    """A realistic JSON-serialized filter string for a run event type."""
    run_filter = json.dumps({"$and": [{"display_name": {"$contains": "my-run"}}]})

    match run_event_type:
        case EventType.RUN_METRIC_THRESHOLD:
            extra_filter = {
                "run_metric_filter": {
                    "threshold_filter": {
                        "name": "my-metric",
                        "agg_op": "AVERAGE",
                        "window_size": 5,
                        "cmp_op": "$gt",
                        "threshold": 0,
                    }
                }
            }
        case EventType.RUN_METRIC_CHANGE:
            extra_filter = {
                "run_metric_filter": {
                    "change_filter": {
                        "name": "my-metric",
                        "agg_op": "AVERAGE",
                        "window_size": 5,
                        "prior_window_size": 5,
                        "change_dir": "ANY",
                        "change_type": "RELATIVE",
                        "change_amount": 123.45,
                    }
                }
            }
        case EventType.RUN_METRIC_ZSCORE:
            extra_filter = {
                "run_metric_filter": {
                    "zscore_filter": {
                        "name": "my-metric",
                        "window_size": 5,
                        "threshold": 3.0,
                        "change_dir": "ANY",
                    }
                }
            }
        case EventType.RUN_STATE:
            extra_filter = {"run_state_filter": {"states": ["FAILED"]}}
        case _:
            raise ValueError(f"Unsupported run event type: {run_event_type!r}")

    return json.dumps({"run_filter": run_filter} | extra_filter)


@fixture
def saved_run_automation(
    automation_id: str,
    run_event_type: EventType,
    run_event_filter_json: str,
    saved_action: SavedAction,
    project: Project,
) -> Automation:
    """A run-event Automation mimicking what the server returns."""
    return Automation(
        id=automation_id,
        created_at="2024-01-01T00:00:00Z",
        updated_at=None,
        name="test-run-automation",
        description="test run event description",
        enabled=True,
        scope=project,
        event=SavedEvent(event_type=run_event_type, filter=run_event_filter_json),
        action=saved_action,
    )
