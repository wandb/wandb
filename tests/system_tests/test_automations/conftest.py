from __future__ import annotations

import secrets
from collections import defaultdict
from string import ascii_lowercase, digits
from typing import Callable, Iterator

import requests
import wandb
from pytest import FixtureRequest, MonkeyPatch, fixture, skip, xfail
from wandb.apis.public import ArtifactCollection, Project
from wandb.apis.public.integrations import WebhookIntegration
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.automations import (
    ActionType,
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
    return wandb.Api()


@fixture(scope="module")
def project(user, api) -> Project:
    """A wandb Project for tests in this module."""
    # Create the project first if it doesn't exist yet
    name = "test-project"
    api.create_project(name=name, entity=user)
    return api.project(name=name, entity=user)


@fixture(scope="module")
def artifact(user, project) -> Artifact:
    with wandb.init(entity=user, project=project.name) as run:
        artifact = Artifact("test-artifact", "dataset")
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
    integration = make_webhook_integration(name, entity, "fake-url")
    yield integration


@fixture
def clear_initial_automations(api: wandb.Api):
    """Request this fixture to remove any saved automations before the test."""
    # There has to be a better way to do this
    for automation in api.automations():
        api.delete_automation(automation)
    yield


@fixture
def remove_final_automations(api: wandb.Api):
    """Request this fixture to remove any saved automations after the test."""
    # There has to be a better way to do this
    yield
    for automation in api.automations():
        api.delete_automation(automation)


@fixture
def server_supported_event_types(api: wandb.Api) -> set[str]:
    """The set of event types supported by the test server."""
    from wandb.sdk.internal.internal_api import Api as InternalApi

    allowed = InternalApi().automation_event_and_action_types_introspection()
    return set(allowed.event_types)


@fixture
def server_supported_action_types(api: wandb.Api) -> set[str]:
    """The set of action types supported by the test server."""
    from wandb.sdk.internal.internal_api import Api as InternalApi

    allowed = InternalApi().automation_event_and_action_types_introspection()
    return set(allowed.action_types)


## ---------------------------------------------------------------------------
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


@fixture(params=sorted(VALID_SCOPE_TYPES), ids=lambda x: x.value)
def scope_type(request: FixtureRequest) -> ScopeType:
    """A fixture that parametrizes over all valid scope types."""
    return request.param


@fixture(params=sorted(VALID_EVENT_TYPES), ids=lambda x: x.value)
def event_type(request: FixtureRequest, scope_type: ScopeType) -> EventType:
    """A fixture that parametrizes over all valid event types."""
    event_type = request.param
    if scope_type in INVALID_SCOPE_BY_EVENT_TYPE[event_type]:
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
    scope_type: ScopeType, artifact_collection: ArtifactCollection, project: Project
):
    if scope_type is ScopeType.ARTIFACT_COLLECTION:
        return artifact_collection
    elif scope_type is ScopeType.PROJECT:
        return project
    raise ValueError(f"Unhandled scope type: {scope_type}")


@fixture
def event(event_type: EventType, scope, server_supported_event_types: set[str]):
    if event_type.value not in server_supported_event_types:
        xfail(f"Server does not support event type: {event_type.value!r}")

    if event_type is EventType.CREATE_ARTIFACT:
        return OnCreateArtifact(
            scope=scope,
        )

    if event_type is EventType.LINK_MODEL:
        return OnLinkArtifact(
            scope=scope,
        )

    if event_type is EventType.ADD_ARTIFACT_ALIAS:
        return OnAddArtifactAlias(
            scope=scope,
        )

    if event_type is EventType.RUN_METRIC:
        return OnRunMetric(
            scope=scope,
            filter=(RunEvent.metric("my-metric").mean(5) > 0)
            & (RunEvent.name.contains("my-run")),
        )

    raise ValueError(f"Unhandled event type: {event_type}")


@fixture
def action(
    action_type: ActionType,
    webhook_integration: WebhookIntegration,
    server_supported_action_types: set[str],
):
    if action_type.value not in server_supported_action_types:
        xfail(f"Server does not support action type: {action_type.value!r}")

    if action_type is ActionType.NOTIFICATION:
        skip("Need to figure out how to set up SlackIntegration for testing in backend")

    if action_type is ActionType.GENERIC_WEBHOOK:
        return DoWebhook.from_integration(
            webhook_integration,
            payload={"my-key": "my-value"},
        )

    if action_type is ActionType.NO_OP:
        return DoNothing()

    raise ValueError(f"Unhandled action type: {action_type}")


@fixture
def automation_name(make_name: Callable[[str], str]) -> str:
    return make_name("test-automation")
