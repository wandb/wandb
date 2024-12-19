from __future__ import annotations

import base64
import json
import secrets
from operator import itemgetter
from typing import Literal
from unittest.mock import Mock

from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import SearchStrategy, integers
from pytest import FixtureRequest, fixture, mark, skip
from pytest_mock import MockerFixture
from wandb.apis import public
from wandb.sdk.automations import NewAutomation
from wandb.sdk.automations._utils import prepare_create_automation_input
from wandb.sdk.automations.actions import ActionType, DoNotification, DoWebhook
from wandb.sdk.automations.events import (
    Agg,
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


DEPRECATED_EVENT_TYPES = {EventType.UPDATE_ARTIFACT_ALIAS}
DEPRECATED_ACTION_TYPES = {ActionType.QUEUE_JOB}

UNSUPPORTED_EVENT_AND_SCOPE_TYPES = {
    (EventType.LINK_MODEL, ScopeType.PROJECT),
    (EventType.RUN_METRIC, ScopeType.ARTIFACT_COLLECTION),
}


@fixture(params=tuple(ScopeType))
def scope_type(request: type[FixtureRequest]) -> ScopeType:
    return request.param


@fixture(params=tuple(e for e in EventType if (e not in DEPRECATED_EVENT_TYPES)))
def event_type(request: type[FixtureRequest], scope_type: ScopeType) -> EventType:
    if (event_type, scope_type) in UNSUPPORTED_EVENT_AND_SCOPE_TYPES:
        skip(f"Not supported: {event_type=} {scope_type=}")
    return request.param


@fixture(params=tuple(e for e in ActionType if (e not in DEPRECATED_ACTION_TYPES)))
def action_type(request: type[FixtureRequest]) -> ActionType:
    return request.param


@fixture
def scope(
    request: type[FixtureRequest], scope_type: ScopeType
) -> public.ArtifactCollection | public.Project:
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
    integration_id = make_graphql_id("Integration")
    if action_type is ActionType.NOTIFICATION:
        return DoNotification(
            integration_id=integration_id,
            title="Test title",
            text="Test message content",
            level="INFO",
        )

    if action_type is ActionType.GENERIC_WEBHOOK:
        return DoWebhook(
            integration_id=integration_id,
            request_payload={},
        )

    if action_type is ActionType.QUEUE_JOB:
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
        "scopeID": scope.id,
        "triggeringEventType": event_type.value,
        "triggeredActionType": action_type.value,
    }

    get_values = itemgetter(*expected.keys())
    assert get_values(expected) == get_values(params)

    if (event_filter_json := params["eventFilter"]) is None:
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
        # Event filter should be valid JSON and equivalent to what's on the original event
        event_filter = json.loads(event_filter_json)
        assert event_filter == event.filter.model_dump()


class TestDeclarativeEventSyntax:
    """Tests for self-consistency of the declarative event syntax."""

    names: SearchStrategy[str] = printable_text()
    window_sizes: SearchStrategy[int] = integers(min_value=1, max_value=100)
    thresholds: SearchStrategy[float] = integers() | finite_floats()

    @settings(suppress_health_check=[HealthCheck.differing_executors])
    @given(name=names, window=window_sizes, threshold=thresholds)
    def test_run_metric_comparison_syntax_is_self_consistent(
        self, name: str, window: int, threshold: float
    ):
        """Check that the built-in comparison syntax is equivalent to the method-call syntax."""
        for metric_expr in (
            # Aggregated
            RunEvent.metric(name).average(window),
            RunEvent.metric(name).mean(window),
            RunEvent.metric(name).min(window),
            RunEvent.metric(name).max(window),
            # Single metric value
            RunEvent.metric(name),
        ):
            assert (metric_expr > threshold) == metric_expr.gt(threshold)
            assert (metric_expr >= threshold) == metric_expr.gte(threshold)
            assert (metric_expr < threshold) == metric_expr.lt(threshold)
            assert (metric_expr <= threshold) == metric_expr.lte(threshold)

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
