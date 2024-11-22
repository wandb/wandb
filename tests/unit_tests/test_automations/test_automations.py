from __future__ import annotations

import base64
import json
from unittest.mock import Mock

from pydantic import PositiveInt
from pytest import fail, fixture, mark
from pytest_mock import MockerFixture
from wandb.apis import public
from wandb.sdk.automations import NewAutomation, events
from wandb.sdk.automations._generated.enums import (
    EventTriggeringConditionType,
    TriggerScopeType,
)
from wandb.sdk.automations._utils import prepare_create_automation_input
from wandb.sdk.automations.actions import DoNotification
from wandb.sdk.automations.events import OnAddArtifactAlias, OnLinkArtifact, OnRunMetric


def generate_graphql_idstr(prefix: str, idx: PositiveInt = 123) -> str:
    """Generate the string "ID" value for a wandb object, enforcing its expected encoding in e.g. a GraphQL response.

    When returned in a GraphQL response, ID values are base64-encoded strings of
    - a named prefix
    - an integer ID

    The original, decoded IDs would have representations such as, e.g.:
    - "Integrations:123"
    - "ArtifactCollection:101"
    - etc.
    """
    return base64.encodebytes(f"{prefix}:{idx:d}".encode()).decode()


@fixture
def mock_client(mocker: MockerFixture) -> Mock:
    """A no-op client for instantiating scope types for unit tests that won't make actual API calls."""
    from wandb.apis.public import RetryingClient

    return mocker.Mock(spec=RetryingClient)


@fixture
def artifact_collection(mocker, mock_client) -> public.ArtifactCollection:
    """Simulates an ArtifactCollection that could be returned by the Api.

    This might be typically fetched via:
    - `Api.artifact_collection()`
    - `Api.artifact().collection`
    - etc.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on "real" wandb.Api calls should live in system tests.
    """

    # ArtifactCollection.load() is called on instantiation, so patch it first as we don't need it here
    mocker.patch.object(public.ArtifactCollection, "load")

    return public.ArtifactCollection(
        client=mock_client,
        entity="test-entity",
        project="test-project",
        name="test-collection",
        type="dataset",
        attrs={
            "id": generate_graphql_idstr(prefix="ArtifactCollection"),
            "aliases": {"edges": []},
            "tags": {"edges": []},
            "description": "This is a fake artifact collection.",
        },
    )


@fixture
def project(mock_client) -> public.Project:
    """Simulates a Project that could be returned by the Api.

    This might be typically fetched via:
    - `Api.project()`
    - `Api.projects()`
    - etc.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on "real" wandb.Api calls should live in system tests.
    """
    return public.Project(
        client=mock_client,
        entity="test-entity",
        project="test-project",
        attrs={
            "id": generate_graphql_idstr(prefix="Project"),
        },
    )


@mark.parametrize(
    "name",
    ["test automation name"],
)
@mark.parametrize(
    "description",
    ["This is a description", None],
)
@mark.parametrize(
    "enabled",
    [True, False],
)
def test_new_link_artifact_automation(artifact_collection, name, description, enabled):
    """Check that we can instantiate a DoAutomation object (without actually sending it to the server)."""

    # TODO: Parameterize this to cover more variations
    _ = OnLinkArtifact(
        scope=artifact_collection,
    )
    event = OnAddArtifactAlias.from_pattern(
        "my-alias",
        scope=artifact_collection,
    )

    action = DoNotification(
        integration_id=generate_graphql_idstr(prefix="Integrations"),
        title="Test title",
        text="Test message content",
        level="INFO",
    )

    # TODO: Consolidate this logic into fewer internal helper functions/methods
    prepared = prepare_create_automation_input(
        NewAutomation.define(
            event >> action,
            name=name,
            description=description,
            enabled=enabled,
        ),
    ).model_dump(by_alias=True, mode="json", round_trip=True)

    assert prepared["name"] == name
    assert prepared["description"] == description
    assert prepared["enabled"] is enabled

    assert prepared["scopeType"] == TriggerScopeType.ARTIFACT_COLLECTION.value
    assert isinstance(prepared["scopeID"], str)
    assert prepared["scopeID"] == artifact_collection.id

    assert (
        prepared["triggeringEventType"]
        == EventTriggeringConditionType.ADD_ARTIFACT_ALIAS.value
    )
    if (event_filter_json := prepared.get("eventFilter")) is not None:
        # Event filter should be valid JSON
        event_filter_dict = json.loads(event_filter_json)

        # As should the individual filters in the next level of nesting (backend API expects this)
        try:
            _ = json.loads(event_filter_dict["filter"])
        except Exception as e:
            fail(
                f"Unable to parse inner JSON from eventFilter: {event_filter_dict}.  Encountered error: {e!r}"
            )


@mark.parametrize(
    "name",
    ["automation-name"],
)
@mark.parametrize(
    "description",
    ["This is a description", None],
)
@mark.parametrize(
    "enabled",
    [True, False],
)
def test_new_run_metric_automation(project, name, description, enabled):
    """Check that we can instantiate a NewAutomation object (without actually sending it to the server)."""

    # TODO: Parameterize this to cover more variations
    event = OnRunMetric(
        scope=project,
        filter=(
            events.RunEvent.name.contains("my-run")
            & events.RunEvent.metric("my-metric").mean(window=5).gt(123.45)
        ),
    )

    action = DoNotification(
        integration_id=generate_graphql_idstr(prefix="Integrations"),
        title="Test title",
        text="Test message content",
        level="INFO",
    )

    prepared = prepare_create_automation_input(
        NewAutomation.define(
            event >> action,
            name=name,
            description=description,
            enabled=enabled,
        ),
    ).model_dump(by_alias=True, mode="json", round_trip=True)

    assert prepared["name"] == name
    assert prepared["description"] == description
    assert prepared["enabled"] is enabled

    assert prepared["scopeType"] == TriggerScopeType.PROJECT.value
    assert isinstance(prepared["scopeID"], str)
    assert prepared["scopeID"] == project.id

    assert (
        prepared["triggeringEventType"] is EventTriggeringConditionType.RUN_METRIC.value
    )
    if prepared.get("eventFilter") is not None:
        # Event filter should be valid JSON
        filter_dict = json.loads(prepared["eventFilter"])

        # And the API expects the run and metric filters to be doubly serialized
        _ = json.loads(filter_dict["run_filter"])
        _ = json.loads(filter_dict["metric_filter"])
