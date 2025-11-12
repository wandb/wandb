from __future__ import annotations

import secrets
from collections.abc import Callable, Generator
from functools import lru_cache
from string import ascii_lowercase, digits
from typing import TYPE_CHECKING, TypeAlias

import wandb
from pytest import FixtureRequest, fixture, skip
from wandb import Artifact
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
    OnRunState,
    OnUnlinkArtifact,
    RunEvent,
    ScopeType,
    SendWebhook,
    WebhookIntegration,
)
from wandb.automations._filters import FilterExpr
from wandb.automations._generated import (
    CREATE_GENERIC_WEBHOOK_INTEGRATION_GQL,
    CreateGenericWebhookIntegration,
)
from wandb.automations._utils import INVALID_INPUT_ACTIONS, INVALID_INPUT_EVENTS
from wandb.automations.events import InputEvent

if TYPE_CHECKING:
    from tests.system_tests.backend_fixtures import BackendFixtureFactory

ScopableWandbType: TypeAlias = (
    ArtifactCollection | Project | Registry | Team | Organization
)


def random_string(chars: str = ascii_lowercase + digits, n: int = 12) -> str:
    """Return a random string of a given length.

    Args:
        chars: A sequence of allowed characters in the generated string.
        n: Length of the string to generate.
    """
    return "".join(secrets.choice(chars) for _ in range(n))


@fixture(scope="module")
def make_name(worker_id: str) -> Callable[[str], str]:
    """A factory fixture for generating unique names."""

    def _make_name(prefix: str) -> str:
        return f"{prefix}-{worker_id}-{random_string()}"

    return _make_name


@fixture(scope="module")
def project(
    module_user: str,
    make_module_api: Callable[[], wandb.Api],
    make_name,
) -> Project:
    """A wandb Project for tests in this module."""
    # Create the project first if it doesn't exist yet
    name = make_name("test-project")
    api = make_module_api()
    api.create_project(name=name, entity=module_user)
    project = api.project(name=name, entity=module_user)
    # This fixture is module-scoped; load attrs before per-test teardown invalidates the API.
    _ = project.id
    return project


@fixture
def registry(
    backend_fixture_factory: BackendFixtureFactory,
    module_user: str,
    module_api: wandb.Api,
    make_name: Callable[[str], str],
) -> Registry:
    organization = backend_fixture_factory.make_org(username=module_user)
    return module_api.create_registry(
        name=make_name("test-registry"),
        visibility="organization",
        organization=organization,
    )


@fixture(scope="module")
def artifact(module_user: str, project: Project, make_name) -> Artifact:
    name = make_name("test-artifact")
    with wandb.init(entity=module_user, project=project.name) as run:
        artifact = Artifact(name, "dataset")
        logged_artifact = run.log_artifact(artifact)
        return logged_artifact.wait()


@fixture(scope="module")
def artifact_collection(
    artifact: Artifact,
    make_module_api: Callable[[], wandb.Api],
) -> ArtifactCollection:
    """A test ArtifactCollection for tests in this module."""
    return (
        make_module_api()
        .artifact(name=artifact.qualified_name, type=artifact.type)
        .collection
    )


@fixture(scope="module")
def team(
    backend_fixture_factory: BackendFixtureFactory,
    module_user: str,
    make_module_api: Callable[[], wandb.Api],
) -> Team:
    """A test team entity for tests in this module."""
    name = backend_fixture_factory.make_team(username=module_user).team
    return make_module_api().team(name)


@fixture(scope="module")
def make_webhook_integration(
    make_module_api: Callable[[], wandb.Api],
) -> Callable[[str, str, str], WebhookIntegration]:
    """A module-scoped factory for creating WebhookIntegrations."""
    from wandb.automations._generated import CreateGenericWebhookIntegrationInput

    # HACK: Set up a placeholder webhook integration and return it
    # At the time of testing/implementation, this is the action with
    # the lowest setup overhead and, if needed, probably least difficult
    # to patch/mock/stub/spy/intercept

    def _make_webhook(name: str, entity: str, url: str) -> WebhookIntegration:
        gql_input = CreateGenericWebhookIntegrationInput(
            name=name, entity_name=entity, url_endpoint=url
        )
        result = (
            make_module_api()
            ._service_api.execute_graphql(
                CREATE_GENERIC_WEBHOOK_INTEGRATION_GQL,
                variables={"input": gql_input.model_dump()},
                parse=CreateGenericWebhookIntegration.model_validate_json,
            )
            .result
        )
        return WebhookIntegration.model_validate(result.integration)

    return _make_webhook


@fixture(scope="module")
def webhook(
    make_module_api: Callable[[], wandb.Api],
    make_webhook_integration: Callable[[str, str, str], WebhookIntegration],
    make_name: Callable[[str], str],
) -> Generator[WebhookIntegration]:
    """A "registered" webhook integration for automation system tests."""
    name = make_name("test-webhook")
    entity = make_module_api().default_entity
    yield make_webhook_integration(
        name=name,
        entity=entity,
        url="https://example.com/webhook",
    )


# ---------------------------------------------------------------------------
# Exclude deprecated events/actions that will not be exposed in the API for programmatic creation
def valid_input_scopes() -> list[ScopeType]:
    # return sorted(ScopeType)  # TODO: restore once ENTITY scope is supported
    return sorted(set(ScopeType) - {ScopeType.ENTITY})


def valid_input_events() -> list[EventType]:
    return sorted(set(EventType) - set(INVALID_INPUT_EVENTS))


def valid_input_actions() -> list[ActionType]:
    # Slack integrations are not configured for these system tests, so
    # notification actions are only exercised by tests that request them
    # explicitly.
    unsupported_test_actions = {ActionType.NOTIFICATION}
    return sorted(
        set(ActionType) - set(INVALID_INPUT_ACTIONS) - unsupported_test_actions
    )


# Invalid (event, scope) combinations that should not produce runnable cases.
@lru_cache
def invalid_events_and_scopes() -> set[tuple[EventType, ScopeType]]:
    return {
        (EventType.CREATE_ARTIFACT, ScopeType.PROJECT),
        (EventType.RUN_METRIC_THRESHOLD, ScopeType.ARTIFACT_COLLECTION),
        (EventType.RUN_METRIC_CHANGE, ScopeType.ARTIFACT_COLLECTION),
        (EventType.RUN_METRIC_ZSCORE, ScopeType.ARTIFACT_COLLECTION),
        (EventType.RUN_STATE, ScopeType.ARTIFACT_COLLECTION),
    }


def pytest_collection_modifyitems(config, items):
    deselected = []
    selected = []
    invalid_pairs = invalid_events_and_scopes()

    for item in items:
        callspec = getattr(item, "callspec", None)
        if callspec is None:
            selected.append(item)
            continue

        event = callspec.params.get("event_type")
        scope = callspec.params.get("scope_type")
        if event is not None and scope is not None and (event, scope) in invalid_pairs:
            deselected.append(item)
            continue

        selected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


@fixture(params=valid_input_scopes(), ids=lambda x: f"scope={x.value}")
def scope_type(request: FixtureRequest, module_api: wandb.Api) -> ScopeType:
    """A fixture that parametrizes over all valid scope types."""
    if not module_api._supports_automation(scope=(scope_type := request.param)):
        skip(f"Server does not support scope type: {scope_type!r}")

    return scope_type


@fixture(params=valid_input_events(), ids=lambda x: f"event={x.value}")
def event_type(
    request: FixtureRequest,
    scope_type: ScopeType,
    module_api: wandb.Api,
) -> EventType:
    """A fixture that parametrizes over all valid event types."""
    if not module_api._supports_automation(event=(event_type := request.param)):
        skip(f"Server does not support event type: {event_type!r}")

    if (event_type, scope_type) in invalid_events_and_scopes():
        skip(f"Event {event_type.value!r} doesn't support scope {scope_type.value!r}")

    return event_type


@fixture(params=valid_input_actions(), ids=lambda x: f"action={x.value}")
def action_type(
    request: type[FixtureRequest],
    module_api: wandb.Api,
) -> ActionType:
    """A fixture that parametrizes over all valid action types."""
    if not module_api._supports_automation(action=(action_type := request.param)):
        skip(f"Server does not support action type: {action_type!r}")

    return action_type


@fixture
def scope(request: FixtureRequest, scope_type: ScopeType) -> ScopableWandbType:
    scope2fixture: dict[ScopeType, str] = {
        ScopeType.ARTIFACT_COLLECTION: artifact_collection.__name__,
        ScopeType.PROJECT: project.__name__,
        ScopeType.ENTITY: team.__name__,
    }
    # We want to request the fixture dynamically, hence the request.getfixturevalue workaround
    return request.getfixturevalue(scope2fixture[scope_type])


# ------------------------------------------------------------------------------
# (Input) event fixtures
@fixture
def alias_filter() -> FilterExpr:
    return ArtifactEvent.alias.matches_regex("^my-artifact.*")


@fixture
def tag_filter() -> FilterExpr:
    return ArtifactEvent.tag.matches_regex("^my-tag.*")


@fixture
def on_create_artifact(scope, alias_filter) -> OnCreateArtifact:
    return OnCreateArtifact(scope=scope, filter=alias_filter)


@fixture
def on_link_artifact(scope, alias_filter) -> OnLinkArtifact:
    return OnLinkArtifact(scope=scope, filter=alias_filter)


@fixture
def on_unlink_artifact(scope, alias_filter) -> OnUnlinkArtifact:
    return OnUnlinkArtifact(scope=scope, filter=alias_filter)


@fixture
def on_add_artifact_alias(scope, alias_filter) -> OnAddArtifactAlias:
    return OnAddArtifactAlias(scope=scope, filter=alias_filter)


@fixture
def on_add_artifact_tag(scope, tag_filter) -> OnAddArtifactTag:
    return OnAddArtifactTag(scope=scope, filter=tag_filter)


@fixture
def on_remove_artifact_tag(scope, tag_filter) -> OnRemoveArtifactTag:
    return OnRemoveArtifactTag(scope=scope, filter=tag_filter)


@fixture
def on_add_collection_tag(scope, tag_filter) -> OnAddCollectionTag:
    return OnAddCollectionTag(scope=scope, filter=tag_filter)


@fixture
def on_remove_collection_tag(scope, tag_filter) -> OnRemoveCollectionTag:
    return OnRemoveCollectionTag(scope=scope, filter=tag_filter)


@fixture
def on_run_metric_threshold(scope) -> OnRunMetric:
    run_filter = RunEvent.name.contains("my-run")
    metric_filter = RunEvent.metric("my-metric").mean(5).gt(0)
    return OnRunMetric(scope=scope, filter=run_filter & metric_filter)


@fixture
def on_run_metric_change(scope) -> OnRunMetric:
    run_filter = RunEvent.name.contains("my-run")
    metric_filter = RunEvent.metric("my-metric").mean(5).changes_by(diff=123.45)
    return OnRunMetric(scope=scope, filter=run_filter & metric_filter)


@fixture
def on_run_metric_zscore(scope) -> OnRunMetric:
    from wandb.automations import MetricZScoreFilter
    from wandb.automations._run_metric_filters import ChangeDir

    run_filter = RunEvent.name.contains("my-run")
    metric_filter = MetricZScoreFilter(
        name="my-metric",
        window=5,
        threshold=2.0,
        change_dir=ChangeDir.ANY,
    )
    return OnRunMetric(scope=scope, filter=run_filter & metric_filter)


@fixture
def on_run_state(scope) -> OnRunState:
    run_filter = RunEvent.name.contains("my-run")
    state_filter = RunEvent.state == "failed"
    return OnRunState(scope=scope, filter=run_filter & state_filter)


@fixture
def event(request: FixtureRequest, event_type: EventType) -> InputEvent:
    """An event object for defining a **new** automation."""
    event2fixture: dict[EventType, str] = {
        EventType.CREATE_ARTIFACT: on_create_artifact.__name__,
        EventType.ADD_ARTIFACT_ALIAS: on_add_artifact_alias.__name__,
        EventType.ADD_ARTIFACT_TAG: on_add_artifact_tag.__name__,
        EventType.ADD_COLLECTION_TAG: on_add_collection_tag.__name__,
        EventType.LINK_ARTIFACT: on_link_artifact.__name__,
        EventType.REMOVE_ARTIFACT_TAG: on_remove_artifact_tag.__name__,
        EventType.REMOVE_COLLECTION_TAG: on_remove_collection_tag.__name__,
        EventType.UNLINK_ARTIFACT: on_unlink_artifact.__name__,
        EventType.RUN_METRIC_THRESHOLD: on_run_metric_threshold.__name__,
        EventType.RUN_METRIC_CHANGE: on_run_metric_change.__name__,
        EventType.RUN_METRIC_ZSCORE: on_run_metric_zscore.__name__,
        EventType.RUN_STATE: on_run_state.__name__,
    }
    return request.getfixturevalue(event2fixture[event_type])


# ------------------------------------------------------------------------------
# (Input) action fixtures
@fixture
def send_notification():
    skip("SlackIntegrations are not currently set up for testing in backend")


@fixture
def send_webhook(webhook: WebhookIntegration) -> SendWebhook:
    return SendWebhook(
        integration_id=webhook.id,
        request_payload={"my-key": "my-value"},
    )


@fixture
def do_nothing() -> DoNothing:
    return DoNothing()


@fixture
def action(request: FixtureRequest, action_type: ActionType):
    """An action object for defining a **new** automation."""
    action2fixture: dict[ActionType, str] = {
        ActionType.NOTIFICATION: send_notification.__name__,
        ActionType.GENERIC_WEBHOOK: send_webhook.__name__,
        ActionType.NO_OP: do_nothing.__name__,
    }
    return request.getfixturevalue(action2fixture[action_type])
