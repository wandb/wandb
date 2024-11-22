from __future__ import annotations

import base64
import json
import secrets
from operator import itemgetter
from typing import Literal
from unittest.mock import Mock

from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import integers
from pytest import FixtureRequest, fixture, mark, raises, skip
from pytest_mock import MockerFixture
from wandb.apis import public
from wandb.sdk.automations import NewAutomation
from wandb.sdk.automations._utils import prepare_create_automation_input
from wandb.sdk.automations.actions import ActionType, DoNotification, DoWebhook
from wandb.sdk.automations.events import (
    EventType,
    MetricFilter,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunEvent,
    RunFilter,
)
from wandb.sdk.automations.scopes import ScopeType

from ._strategies import finite_floats, printable_text


def random_int_id() -> int:
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


@fixture(scope="module")
def mock_client(session_mocker: MockerFixture) -> Mock:
    """A no-op client for instantiating scope types for unit tests that won't make actual API calls."""
    from wandb.apis.public import RetryingClient

    return session_mocker.Mock(spec=RetryingClient)


@fixture(scope="module")
def artifact_collection(
    session_mocker: MockerFixture,
    mock_client: Mock,
) -> public.ArtifactCollection:
    """Simulates an ArtifactCollection that could be returned by the Api.

    This might be typically fetched via `Api.artifact_collection()`, `Api.artifact().collection`, etc.

    For unit-testing purposes, this has been heavily mocked.
    Tests relying on real `wandb.Api` calls should live in system tests.
    """

    # ArtifactCollection.load() is called on instantiation, so patch it to avoid
    # making a live API call
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


@fixture(scope="module")
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
        return OnAddArtifactAlias(scope=scope)

    if event_type is EventType.LINK_MODEL:
        return OnLinkArtifact(scope=scope)

    if event_type is EventType.RUN_METRIC:
        metric_filter = RunEvent.metric("my-metric").mean(window=5).gt(123.45)
        return OnRunMetric(scope=scope, filter=metric_filter)

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

    raise ValueError(f"Unhandled: {action_type=}")


@mark.parametrize("name", argvalues=["test automation name"])
@mark.parametrize("description", argvalues=["This is a description", None])
@mark.parametrize("enabled", argvalues=[True, False], ids=["enabled", "disabled"])
def test_define_new_automation(
    scope: public.ArtifactCollection | public.Project,
    scope_type: ScopeType,
    event: OnCreateArtifact | OnLinkArtifact | OnAddArtifactAlias,
    event_type: EventType,
    action: DoNotification | DoWebhook,
    action_type: ActionType,
    name: Literal["test automation name"],
    description: None | Literal["This is a description"],
    enabled: bool,
):
    """Check that we can instantiate a newly defined Autoamtion (without actually sending it to the server)."""
    defined_automation = NewAutomation.define(
        event >> action,
        name=name,
        description=description,
        enabled=enabled,
    )

    # If we were to actually send this new Automation to the server, these would be the GraphQL request parameters
    input_params = prepare_create_automation_input(defined_automation).model_dump()

    expected_params = {
        "name": name,
        "description": description,
        "enabled": enabled,
        "scopeType": scope_type.value,
        "scopeID": scope.id,
        "triggeringEventType": event_type.value,
        "triggeredActionType": action_type.value,
    }

    get_values = itemgetter(*expected_params)
    assert get_values(expected_params) == get_values(input_params)

    if (event_filter_json := input_params["eventFilter"]) is not None:
        pass
    elif event_type is EventType.RUN_METRIC:
        event_filter = json.loads(event_filter_json)

        run_filter = json.loads(event_filter["run_filter"])
        metric_filter = json.loads(event_filter["metric_filter"])

        assert isinstance(run_filter, dict)
        assert isinstance(metric_filter, dict)

        assert run_filter.keys() == {"$and"}
        assert metric_filter.keys() == {
            "agg_op",
            "cmp_op",
            "threshold",
            "name",
            "window_size",
        }

    else:
        # Event filter should be valid JSON and match what was passed the original event
        assert json.loads(event_filter_json) == event.filter.model_dump()


class TestDeclarativeEventSyntax:
    """Tests for self-consistency of the declarative event syntax."""

    @settings(suppress_health_check=[HealthCheck.differing_executors])
    @given(
        name=printable_text(),
        window=integers(min_value=1, max_value=100),
        threshold=integers() | finite_floats(),
    )
    def test_run_metric_operator_vs_method_syntax_is_equivalent(
        self, name: str, window: int, threshold: float
    ):
        """Check that metric thresholds defined via comparison operators vs method-call syntax are equivalent."""
        metric_expressions = [
            RunEvent.metric(name).average(window),  # Aggregate
            RunEvent.metric(name).mean(window),  # Aggregate
            RunEvent.metric(name).min(window),  # Aggregate
            RunEvent.metric(name).max(window),  # Aggregate
            RunEvent.metric(name),  # Single value
        ]

        for metric_expr in metric_expressions:
            assert (metric_expr > threshold) == metric_expr.gt(threshold)
            assert (metric_expr >= threshold) == metric_expr.gte(threshold)
            assert (metric_expr < threshold) == metric_expr.lt(threshold)
            assert (metric_expr <= threshold) == metric_expr.lte(threshold)

    def test_run_metric_threshold_cannot_be_aggregated_twice(self):
        """Check that run metric thresholds forbid multiple aggregations."""
        with raises(ValueError):
            RunEvent.metric("my-metric").average(5).average(10)

        with raises(ValueError):
            RunEvent.metric("my-metric").average(10).max(5)

    def test_declarative_run_metric_events(self, project: public.Project):
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

        metric_filter = RunEvent.metric(name).average(window).gt(threshold)

        # Check that the metric filter has both the expected contents and human-readable representation
        assert f"{agg}(`{name}`) > {threshold}" in repr(metric_filter)
        assert expected_metric_filter == metric_filter

        # Check that the metric filter is parsed/validated correctly by pydantic
        event = OnRunMetric(
            scope=project,
            filter=metric_filter,
        )
        assert RunFilter() == event.filter.run_filter
        assert expected_metric_filter == event.filter.metric_filter

        # Check that the run+metric filter is parsed/validated correctly by pydantic
        run_filter = RunEvent.name.contains("my-run")
        metric_filter = RunEvent.metric(name).average(window).gt(threshold)
        event = OnRunMetric(
            scope=project,
            filter=run_filter & metric_filter,
        )

        expected_run_filter_dict = {"$and": [{"display_name": {"$contains": "my-run"}}]}
        expected_run_filter = RunFilter.model_validate(expected_run_filter_dict)

        assert expected_run_filter_dict == event.filter.run_filter.model_dump()
        assert expected_run_filter == event.filter.run_filter
        assert expected_metric_filter == event.filter.metric_filter
