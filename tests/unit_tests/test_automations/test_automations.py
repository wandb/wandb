from __future__ import annotations

import base64
import json
from unittest.mock import Mock

from hypothesis import given
from hypothesis.strategies import integers
from pydantic import PositiveInt
from pytest import fixture, mark, skip
from pytest_mock import MockerFixture
from wandb.apis import public
from wandb.sdk.automations import NewAutomation
from wandb.sdk.automations._generated import (
    EventTriggeringConditionType,
    TriggeredActionType,
    TriggerScopeType,
)
from wandb.sdk.automations._utils import prepare_create_automation_input
from wandb.sdk.automations.actions import DoLaunchJob, DoNotification, DoWebhook
from wandb.sdk.automations.events import (
    Agg,
    MetricFilter,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunEvent,
    RunFilter,
)

from ._strategies import finite_floats, printable_text

pytestmark = [
    mark.wandb_core_only,  # Nothing here makes live requests, avoid testing twice
]


def make_graphql_id(prefix: str, idx: PositiveInt = 123) -> str:
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


@fixture(scope="session")
def mock_client(session_mocker: MockerFixture) -> Mock:
    """A no-op client for instantiating scope types for unit tests that won't make actual API calls."""
    from wandb.apis.public import RetryingClient

    return session_mocker.Mock(spec=RetryingClient)


@fixture(scope="session")
def artifact_collection(session_mocker, mock_client) -> public.ArtifactCollection:
    """Simulates an ArtifactCollection that could be returned by the Api.

    This might be typically fetched via:
    - `Api.artifact_collection()`
    - `Api.artifact().collection`
    - etc.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on "real" wandb.Api calls should live in system tests.
    """

    # ArtifactCollection.load() is called on instantiation, so patch it first as we don't need it here
    session_mocker.patch.object(public.ArtifactCollection, "load")

    return public.ArtifactCollection(
        client=mock_client,
        entity="test-entity",
        project="test-project",
        name="test-collection",
        type="dataset",
        attrs={
            "id": make_graphql_id(prefix="ArtifactCollection"),
            "aliases": {"edges": []},
            "tags": {"edges": []},
            "description": "This is a fake artifact collection.",
        },
    )


@fixture(scope="session")
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
            "id": make_graphql_id(prefix="Project"),
        },
    )


@fixture(
    params=[
        TriggerScopeType.ARTIFACT_COLLECTION,
        TriggerScopeType.PROJECT,
    ]
)
def scope_type(request) -> TriggerScopeType:
    return request.param


@fixture(
    params=[
        EventTriggeringConditionType.CREATE_ARTIFACT,
        EventTriggeringConditionType.ADD_ARTIFACT_ALIAS,
        EventTriggeringConditionType.LINK_MODEL,
        # EventTriggeringConditionType.RUN_METRIC,
    ]
)
def event_type(request) -> EventTriggeringConditionType:
    return request.param


@fixture(
    params=[
        TriggeredActionType.NOTIFICATION,
        # TriggeredActionType.GENERIC_WEBHOOK,
        # TriggeredActionType.QUEUE_JOB,
    ]
)
def action_type(request) -> TriggeredActionType:
    return request.param


@fixture
def event(
    artifact_collection,
    event_type,
    scope_type,
) -> OnCreateArtifact | OnLinkArtifact | OnAddArtifactAlias:
    if event_type is EventTriggeringConditionType.CREATE_ARTIFACT:
        if scope_type is TriggerScopeType.ARTIFACT_COLLECTION:
            return OnCreateArtifact(
                scope=artifact_collection,
            )
        else:
            skip("Not implemented/supported")
    if event_type is EventTriggeringConditionType.ADD_ARTIFACT_ALIAS:
        if scope_type is TriggerScopeType.ARTIFACT_COLLECTION:
            return OnAddArtifactAlias.from_pattern(
                "my-alias",
                scope=artifact_collection,
            )
        else:
            skip("Not implemented/supported")
    if event_type is EventTriggeringConditionType.LINK_MODEL:
        if scope_type is TriggerScopeType.ARTIFACT_COLLECTION:
            return OnLinkArtifact(
                scope=artifact_collection,
            )
        else:
            skip("Not implemented/supported")

    raise ValueError(f"Unhandled: {event_type=}")


@fixture
def action(action_type) -> DoNotification | DoWebhook | DoLaunchJob:
    if action_type is TriggeredActionType.NOTIFICATION:
        return DoNotification(
            integration_id=make_graphql_id(prefix="Integrations"),
            title="Test title",
            text="Test message content",
            level="INFO",
        )
    if action_type is TriggeredActionType.GENERIC_WEBHOOK:
        skip("Not implemented/supported")
    if action_type is TriggeredActionType.QUEUE_JOB:
        skip("Not implemented/supported")

    raise ValueError(f"Unhandled: {action_type=}")


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
    ids=["enabled", "disabled"],
)
def test_define_new_automation(
    artifact_collection,
    scope_type,
    event,
    event_type,
    action,
    action_type,
    name,
    description,
    enabled,
):
    """Check that we can instantiate a newly defined Autoamtion (without actually sending it to the server)."""
    params = prepare_create_automation_input(
        NewAutomation.define(
            event >> action,
            name=name,
            description=description,
            enabled=enabled,
        ),
    ).model_dump()

    expected = {
        "name": name,
        "description": description,
        "enabled": enabled,
        "scopeType": scope_type.value,
        "scopeID": str(artifact_collection.id),
        "triggeringEventType": event_type.value,
        "triggeredActionType": action_type.value,
    }

    for key, expected_val in expected.items():
        assert params[key] == expected_val

    if (event_filter_json := params["eventFilter"]) is not None:
        # Event filter should be valid JSON
        prepared_filter = json.loads(event_filter_json)
        assert prepared_filter == event.filter.model_dump()


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
            RunEvent.name.contains("my-run")
            & RunEvent.metric("my-metric").mean(window=5).gt(123.45)
        ),
    )
    event = OnRunMetric(
        scope=project,
        filter=(
            # RunEvent.name.contains("my-run")
            RunEvent.metric("my-metric").mean(window=5).gt(123.45)
        ),
    )

    action = DoNotification(
        integration_id=make_graphql_id(prefix="Integrations"),
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


class TestDeclarativeEventSyntax:
    @given(
        name=printable_text,
        window=integers(min_value=1, max_value=10),
        threshold=integers() | finite_floats,
    )
    def test_equivalent_cmp_operators_vs_method_syntax(self, name, window, threshold):
        left_operand = RunEvent.metric(name).average(window)
        assert (left_operand > threshold) == left_operand.gt(threshold)
        assert (left_operand < threshold) == left_operand.lt(threshold)
        assert (left_operand >= threshold) == left_operand.gte(threshold)
        assert (left_operand <= threshold) == left_operand.lte(threshold)

    def test_declarative_run_metric_events(self, project):
        name = "my-metric"
        window = 5
        agg = "AVERAGE"
        cmp = "$gt"
        threshold = 123.45

        expected_metric_filter = MetricFilter(
            name=name,
            window_size=window,
            agg_op=agg,
            cmp_op=cmp,
            threshold=threshold,
        )

        metric_filter_arg = RunEvent.metric(name).average(window) > threshold
        assert expected_metric_filter == metric_filter_arg

        event = OnRunMetric(scope=project, filter=metric_filter_arg)
        actual_run_filter = event.filter.run_filter
        actual_metric_filter = event.filter.metric_filter

        assert RunFilter() == actual_run_filter
        assert expected_metric_filter == actual_metric_filter

        aggfunc_name = Agg(agg).value
        expected_metric_repr = f"{aggfunc_name}(`{name}`) > {threshold}"
        assert expected_metric_repr in repr(actual_metric_filter)

        expected_run_filter = RunFilter.model_validate(
            {"$and": [{"display_name": {"$contains": "my-run"}}]}
        )
        event = OnRunMetric(
            scope=project,
            filter=(
                RunEvent.name.contains("my-run")
                & RunEvent.metric(name).mean(window).gt(threshold)
            ),
        )

        assert expected_run_filter == event.filter.run_filter
        assert expected_metric_filter == event.filter.metric_filter
