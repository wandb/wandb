from __future__ import annotations

import secrets
from functools import lru_cache
from string import ascii_lowercase, digits
from typing import Callable, Iterator, Union

import wandb
from pytest import FixtureRequest, MonkeyPatch, fixture, skip, xfail
from typing_extensions import TypeAlias
from wandb import Artifact
from wandb.apis.public import ArtifactCollection, Project
from wandb.automations import (
    ActionType,
    ArtifactEvent,
    DoNothing,
    EventType,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
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
from wandb.automations._utils import EXCLUDED_INPUT_ACTIONS, EXCLUDED_INPUT_EVENTS
from wandb.automations.events import InputEvent
from wandb_gql import gql

ScopableWandbType: TypeAlias = Union[ArtifactCollection, Project]


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
def user(backend_fixture_factory) -> Iterator[str]:
    """A module-scoped user that overrides the default `user` fixture from the root-level `conftest.py`."""
    username = backend_fixture_factory.make_user(admin=True)

    # The `monkeypatch` fixture is strictly function-scoped, so we use a
    # context manager to patch for this module-scoped fixture
    envvars = dict.fromkeys(
        ("WANDB_API_KEY", "WANDB_ENTITY", "WANDB_USERNAME"), username
    )
    with MonkeyPatch.context() as mpatch:
        for k, v in envvars.items():
            mpatch.setenv(k, v)
        yield username


# Request the `user` fixture to ensure env variables are set
@fixture(scope="module")
def api(user: str) -> wandb.Api:
    """A redefined, module-scoped `Api` fixture for tests in this module.

    Note that this overrides the default `api` fixture from the root-level
    `conftest.py`.  This is necessary for any tests in these subfolders,
    since the default `api` fixture is function-scoped, meaning it does not
    play well with other module-scoped fixtures.
    """
    return wandb.Api()


@fixture(scope="module")
def project(user, api, make_name) -> Project:
    """A wandb Project for tests in this module."""
    # Create the project first if it doesn't exist yet
    name = make_name("test-project")
    api.create_project(name=name, entity=user)
    return api.project(name=name, entity=user)


@fixture(scope="module")
def artifact(user, project, make_name) -> Artifact:
    name = make_name("test-artifact")
    with wandb.init(entity=user, project=project.name) as run:
        artifact = Artifact(name, "dataset")
        logged_artifact = run.log_artifact(artifact)
        return logged_artifact.wait()


@fixture(scope="module")
def artifact_collection(artifact, api) -> ArtifactCollection:
    """A test ArtifactCollection for tests in this module."""
    return api.artifact(name=artifact.qualified_name, type=artifact.type).collection


@fixture(scope="module")
def make_webhook_integration(
    api: wandb.Api,
) -> Callable[[str, str, str], WebhookIntegration]:
    """A module-scoped factory for creating WebhookIntegrations."""

    # HACK: Set up a placeholder webhook integration and return it
    # At the time of testing/implementation, this is the action with
    # the lowest setup overhead and, if needed, probably least difficult
    # to patch/mock/stub/spy/intercept

    def _make_webhook(name: str, entity: str, url: str) -> WebhookIntegration:
        params = {"name": name, "entityName": entity, "urlEndpoint": url}
        data = api.client.execute(
            gql(CREATE_GENERIC_WEBHOOK_INTEGRATION_GQL),
            variable_values={"params": params},
        )

        result = CreateGenericWebhookIntegration(**data)
        integration = result.create_generic_webhook_integration.integration
        return WebhookIntegration.model_validate(integration)

    return _make_webhook


@fixture(scope="module")
def webhook(
    api,
    make_webhook_integration: Callable[[str, str, str], WebhookIntegration],
    make_name: Callable[[str], str],
) -> Iterator[WebhookIntegration]:
    """A "registered" webhook integration for automation system tests."""
    name = make_name("test-webhook")
    entity = api.default_entity
    yield make_webhook_integration(name=name, entity=entity, url="fake-url")


# ---------------------------------------------------------------------------
# Exclude deprecated events/actions that will not be exposed in the API for programmatic creation
def valid_input_scopes() -> list[ScopeType]:
    return sorted(ScopeType)


def valid_input_events() -> list[EventType]:
    return sorted(set(EventType) - EXCLUDED_INPUT_EVENTS)


def valid_input_actions() -> list[ActionType]:
    return sorted(set(ActionType) - EXCLUDED_INPUT_ACTIONS)


# Invalid (event, scope) combinations that should be skipped
@lru_cache(maxsize=None)
def invalid_events_and_scopes() -> set[tuple[EventType, ScopeType]]:
    return {
        (EventType.CREATE_ARTIFACT, ScopeType.PROJECT),
        (EventType.RUN_METRIC_THRESHOLD, ScopeType.ARTIFACT_COLLECTION),
    }


@fixture(params=valid_input_scopes(), ids=lambda x: f"SCOPE[{x.value}]")
def scope_type(request: FixtureRequest) -> ScopeType:
    """A fixture that parametrizes over all valid scope types."""
    return request.param


@fixture(params=valid_input_events(), ids=lambda x: f"EVENT[{x.value}]")
def event_type(
    request: FixtureRequest, scope_type: ScopeType, api: wandb.Api
) -> EventType:
    """A fixture that parametrizes over all valid event types."""

    event_type = request.param

    if not api._supports_automation(event=event_type):
        skip(f"Server does not support event type: {event_type!r}")

    if (event_type, scope_type) in invalid_events_and_scopes():
        skip(f"Event {event_type.value!r} doesn't support scope {scope_type.value!r}")

    if event_type is EventType.RUN_METRIC_CHANGE:
        xfail(f"Event {event_type.value!r} not yet supported")

    return event_type


@fixture(params=valid_input_actions(), ids=lambda x: f"ACTION[{x.value}]")
def action_type(request: type[FixtureRequest], api: wandb.Api) -> ActionType:
    """A fixture that parametrizes over all valid action types."""
    action_type = request.param

    if not api._supports_automation(action=action_type):
        skip(f"Server does not support action type: {action_type!r}")

    return action_type


@fixture
def scope(request: FixtureRequest, scope_type: ScopeType) -> ScopableWandbType:
    scope2fixture: dict[ScopeType, str] = {
        ScopeType.ARTIFACT_COLLECTION: artifact_collection.__name__,
        ScopeType.PROJECT: project.__name__,
    }
    # We want to request the fixture dynamically, hence the request.getfixturevalue workaround
    return request.getfixturevalue(scope2fixture[scope_type])


# ------------------------------------------------------------------------------
# (Input) event fixtures
@fixture
def artifact_filter() -> FilterExpr:
    return ArtifactEvent.alias.matches_regex("^my-artifact.*")


@fixture
def on_create_artifact(scope, artifact_filter) -> OnCreateArtifact:
    return OnCreateArtifact(scope=scope, filter=artifact_filter)


@fixture
def on_link_artifact(scope, artifact_filter) -> OnLinkArtifact:
    return OnLinkArtifact(scope=scope, filter=artifact_filter)


@fixture
def on_add_artifact_alias(scope, artifact_filter) -> OnAddArtifactAlias:
    return OnAddArtifactAlias(scope=scope, filter=artifact_filter)


@fixture
def on_run_metric(scope) -> OnRunMetric:
    run_filter = RunEvent.name.contains("my-run")
    metric_filter = RunEvent.metric("my-metric").mean(5).gt(0)
    return OnRunMetric(scope=scope, filter=run_filter & metric_filter)


@fixture
def event(request: FixtureRequest, event_type: EventType) -> InputEvent:
    """An event object for defining a **new** automation."""
    event2fixture: dict[EventType, str] = {
        EventType.CREATE_ARTIFACT: on_create_artifact.__name__,
        EventType.ADD_ARTIFACT_ALIAS: on_add_artifact_alias.__name__,
        EventType.LINK_ARTIFACT: on_link_artifact.__name__,
        EventType.RUN_METRIC_THRESHOLD: on_run_metric.__name__,
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
