from __future__ import annotations

import secrets
from collections import defaultdict
from string import ascii_lowercase, digits
from typing import Callable, Iterator

import requests
import wandb
from pytest import FixtureRequest, MonkeyPatch, fixture, skip
from wandb.apis.public import ArtifactCollection, Project
from wandb.apis.public.integrations import WebhookIntegration
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.automations import (
    ActionType,
    ArtifactEvent,
    DoNothing,
    DoWebhook,
    EventType,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunEvent,
    ScopeType,
)
from wandb.sdk.automations._generated import (
    CREATE_GENERIC_WEBHOOK_INTEGRATION_GQL,
    CreateGenericWebhookIntegration,
)


def random_string(alphabet: str = ascii_lowercase + digits, length: int = 12) -> str:
    """Generate a random string of a given length.

    Args:
        alphabet: A sequence of allowed characters in the generated string.
        length: Length of the string to generate.

    Returns:
        A random string.
    """
    return "".join(secrets.choice(alphabet) for _ in range(length))


@fixture(scope="module")
def make_name(worker_id: str) -> Callable[[str], str]:
    """A factory fixture for generating unique names."""

    def _make_name(prefix: str) -> str:
        return f"{prefix}-{worker_id}-{random_string()}"

    return _make_name


@fixture(scope="module")
def user(module_mocker, backend_fixture_factory) -> Iterator[str]:
    """A module-scoped user that overrides the default `user` fixture from the root-level `conftest.py`."""
    username = backend_fixture_factory.make_user(admin=True)
    with MonkeyPatch.context() as module_monkeypatch:
        module_monkeypatch.setenv("WANDB_API_KEY", username)
        module_monkeypatch.setenv("WANDB_ENTITY", username)
        module_monkeypatch.setenv("WANDB_USERNAME", username)
        yield username


@fixture(scope="module")
def api(user) -> wandb.Api:
    """A redefined, module-scoped `Api` fixture for tests in this module.

    Note that this overrides the default `api` fixture from the root-level
    `conftest.py`.  This is necessary for any tests in these subfolders,
    since the default `api` fixture is function-scoped, meaning it does not
    play well with other module-scoped fixtures.
    """
    _ = user  # Request the `user` fixture to ensure env variables are set
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
    from wandb_gql import gql

    # HACK: Set up a placeholder webhook integration and return it
    # At the time of testing/implementation, this is the action with
    # the lowest setup overhead and, if needed, probably least difficult
    # to patch/mock/stub/spy/intercept

    def _make_webhook_integration(
        name: str, entity: str, url: str
    ) -> WebhookIntegration:
        try:
            data = api.client.execute(
                gql(CREATE_GENERIC_WEBHOOK_INTEGRATION_GQL),
                variable_values={
                    "params": {
                        "name": name,
                        "entityName": entity,
                        "urlEndpoint": url,
                    }
                },
            )
        except requests.HTTPError as e:
            raise ValueError(
                f"Failed to create webhook integration ({e!r}): {e.response.json()}"
            ) from e

        result = CreateGenericWebhookIntegration.model_validate(data)
        return WebhookIntegration.model_validate(
            result.create_generic_webhook_integration.integration
        )

    return _make_webhook_integration


@fixture
def webhook_integration(
    api,
    make_webhook_integration: Callable[[str, str, str], WebhookIntegration],
    make_name: Callable[[str], str],
) -> Iterator[WebhookIntegration]:
    name = make_name("test-webhook")
    entity = api.default_entity
    yield make_webhook_integration(name, entity, "fake-url")


@fixture
def clear_initial_automations(api: wandb.Api):
    """Request this fixture to remove any saved automations before the test."""
    # There has to be a better way to do this
    for automation in api.automations():
        api.delete_automation(automation)
    yield


@fixture(scope="module")
def server_supported_automation_types(api: wandb.Api):
    """The sets of event and action types supported by the test server."""
    return api._supported_automation_types()


@fixture
def server_supported_event_types(server_supported_automation_types):
    return server_supported_automation_types.event_types


@fixture
def server_supported_action_types(server_supported_automation_types):
    return server_supported_automation_types.action_types


# ---------------------------------------------------------------------------
# Deprecated events/actions that will not be exposed in the API for programmatic creation
DEPRECATED_EVENT_TYPES = {EventType.UPDATE_ARTIFACT_ALIAS}
DEPRECATED_ACTION_TYPES = {ActionType.QUEUE_JOB}

VALID_SCOPE_TYPES = set(ScopeType)
VALID_EVENT_TYPES = set(EventType) - DEPRECATED_EVENT_TYPES
VALID_ACTION_TYPES = set(ActionType) - DEPRECATED_ACTION_TYPES

# Invalid scope types, if any, for each event type
INVALID_SCOPE_BY_EVENT_TYPE: defaultdict[EventType, set[ScopeType]] = defaultdict(
    set,
    {
        EventType.LINK_MODEL: {ScopeType.PROJECT},
        EventType.RUN_METRIC: {ScopeType.ARTIFACT_COLLECTION},
    },
)


@fixture(params=sorted(VALID_SCOPE_TYPES), ids=lambda x: f"SCOPE[{x.value}]")
def scope_type(request: FixtureRequest) -> ScopeType:
    """A fixture that parametrizes over all valid scope types."""
    return request.param


@fixture(params=sorted(VALID_EVENT_TYPES), ids=lambda x: f"EVENT[{x.value}]")
def event_type(
    request: FixtureRequest,
    scope_type: ScopeType,
    server_supported_event_types: set[EventType],
) -> EventType:
    """A fixture that parametrizes over all valid event types."""
    event_type = request.param

    if event_type not in server_supported_event_types:
        skip(f"Server does not support event type: {event_type!r}")

    if scope_type in INVALID_SCOPE_BY_EVENT_TYPE[event_type]:
        skip(f"Event type {event_type!r} doesn't support scope type {scope_type!r}")

    return event_type


@fixture(params=sorted(VALID_ACTION_TYPES), ids=lambda x: f"ACTION[{x.value}]")
def action_type(
    request: type[FixtureRequest],
    server_supported_action_types: set[ActionType],
) -> ActionType:
    """A fixture that parametrizes over all valid action types."""
    action_type = request.param

    if action_type not in server_supported_action_types:
        skip(f"Server does not support action type: {action_type!r}")

    return action_type


SCOPE_TO_FIXTURENAME: dict[ScopeType, str] = {
    ScopeType.ARTIFACT_COLLECTION: artifact_collection.__name__,
    ScopeType.PROJECT: project.__name__,
}


@fixture
def scope(request: FixtureRequest, event_type: EventType, scope_type: ScopeType):
    # We want to request the fixture dynamically, hence the request.getfixturevalue workaround
    fixturename = SCOPE_TO_FIXTURENAME[scope_type]
    return request.getfixturevalue(fixturename)


# ------------------------------------------------------------------------------
# (Input) event fixtures
@fixture
def on_create_artifact(scope) -> OnCreateArtifact:
    artifact_filter = ArtifactEvent.alias.matches_regex("^my-artifact.*")
    return OnCreateArtifact(scope=scope, filter=artifact_filter)


@fixture
def on_link_artifact(scope) -> OnLinkArtifact:
    artifact_filter = ArtifactEvent.alias.matches_regex("^my-artifact.*")
    return OnLinkArtifact(scope=scope, filter=artifact_filter)


@fixture
def on_add_artifact_alias(scope) -> OnAddArtifactAlias:
    artifact_filter = ArtifactEvent.alias.matches_regex("^my-artifact.*")
    return OnAddArtifactAlias(scope=scope, filter=artifact_filter)


@fixture
def on_run_metric(scope) -> OnRunMetric:
    run_filter = RunEvent.name.contains("my-run")
    metric_filter = RunEvent.metric("my-metric").mean(5).gt(0)
    return OnRunMetric(scope=scope, filter=run_filter & metric_filter)


EVENT_TO_FIXTURENAME: dict[EventType, str] = {
    EventType.CREATE_ARTIFACT: on_create_artifact.__name__,
    EventType.LINK_MODEL: on_link_artifact.__name__,
    EventType.ADD_ARTIFACT_ALIAS: on_add_artifact_alias.__name__,
    EventType.RUN_METRIC: on_run_metric.__name__,
}


@fixture
def event(request: FixtureRequest, event_type: EventType):
    fixturename = EVENT_TO_FIXTURENAME[event_type]
    return request.getfixturevalue(fixturename)


# ------------------------------------------------------------------------------
# (Input) action fixtures
@fixture
def do_notification():
    skip("Need to figure out how to set up SlackIntegration for testing in backend")


@fixture
def do_webhook(webhook_integration: WebhookIntegration) -> DoWebhook:
    return DoWebhook.from_integration(
        webhook_integration,
        payload={"my-key": "my-value"},
    )


@fixture
def do_nothing() -> DoNothing:
    return DoNothing()


ACTION_TO_FIXTURENAME: dict[ActionType, str] = {
    ActionType.NOTIFICATION: do_notification.__name__,
    ActionType.GENERIC_WEBHOOK: do_webhook.__name__,
    ActionType.NO_OP: do_nothing.__name__,
}


@fixture
def action(request: FixtureRequest, action_type: ActionType):
    fixturename = ACTION_TO_FIXTURENAME[action_type]
    return request.getfixturevalue(fixturename)
