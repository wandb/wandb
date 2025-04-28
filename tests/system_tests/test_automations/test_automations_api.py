from __future__ import annotations

import math
from collections import deque
from contextlib import nullcontext
from typing import Any, Callable

import requests
import wandb
from pytest import FixtureRequest, fixture, mark, raises, skip
from wandb.apis.public import ArtifactCollection, Project
from wandb.automations import (
    ActionType,
    Automation,
    DoNothing,
    EventType,
    OnLinkArtifact,
    OnRunMetric,
    ProjectScope,
    RunEvent,
    SendWebhook,
    WebhookIntegration,
)
from wandb.automations.actions import SavedNoOpAction, SavedWebhookAction
from wandb.automations.events import MetricThresholdFilter, RunMetricFilter
from wandb.automations.scopes import ArtifactCollectionScopeTypes


@fixture
def automation_name(make_name: Callable[[str], str]) -> str:
    return make_name(prefix="test-automation")


@fixture
def reset_automations(api: wandb.Api):
    """Request this fixture to remove any saved automations both before and after the test."""
    # There has to be a better way to do this
    for automation in api.automations():
        api.delete_automation(automation)
    yield
    for automation in api.automations():
        api.delete_automation(automation)


# ------------------------------------------------------------------------------
def test_no_initial_automations(api: wandb.Api, reset_automations):
    """No automations should be fetched by the API prior to creating any."""
    assert list(api.automations()) == []


def test_no_initial_integrations(user, api: wandb.Api):
    """No automations should be fetched by the API prior to creating any."""
    assert list(api.integrations()) == []
    assert list(api.slack_integrations()) == []
    assert list(api.webhook_integrations()) == []


def test_fetch_webhook_integrations(
    user, api: wandb.Api, make_name, make_webhook_integration
):
    """Test fetching webhook integrations."""
    # Create multiple webhook integrations
    created_hooks = [
        make_webhook_integration(
            name=make_name("test-webhook"),
            entity=api.default_entity,
            url="fake-url",
        )
        for _ in range(3)
    ]
    created_hooks_by_name = {wh.name: wh for wh in created_hooks}

    fetched_hooks = list(api.webhook_integrations(entity=api.default_entity))
    filtered_hooks = [wh for wh in fetched_hooks if wh.name in created_hooks_by_name]

    assert len(filtered_hooks) == len(created_hooks)

    for fetched_hook in filtered_hooks:
        orig_hook = created_hooks_by_name[fetched_hook.name]

        assert orig_hook.name == fetched_hook.name
        assert orig_hook.url_endpoint == fetched_hook.url_endpoint


def test_fetch_slack_integrations(
    user, api: wandb.Api, make_name, make_webhook_integration
):
    """Test fetching slack integrations."""
    # We don't currently have an easy way of creating real Slack integrations in the backend
    # for system tests, but at least test that the API call doesn't error out.

    # Create a webhook integration only to check that it's omitted from slack_integrations()
    make_webhook_integration(
        name=make_name("test-webhook"),
        entity=api.default_entity,
        url="fake-url",
    )

    # Fetch the slack integrations (for now there won't be any)
    fetched_slack_integrations = list(api.slack_integrations(entity=api.default_entity))
    assert len(fetched_slack_integrations) == 0


@mark.usefixtures(reset_automations.__name__)
def test_create_automation(
    user: str,
    api: wandb.Api,
    event,
    action,
    automation_name: str,
):
    created = api.create_automation(
        (event >> action),
        name=automation_name,
        description="test-description",
    )

    # We should be able to fetch the automation by name (optionally filtering by entity)
    assert created.name == automation_name

    fetched_a = api.automation(entity=user, name=created.name)
    fetched_b = api.automation(name=created.name)

    # NOTE: On older server versions, the ID returned returned by create_automation()
    # seems to have an (encoded) index that's off by 1, vs. the ID returned by
    # automation().
    # This seems fixed on newer servers.  Use server support for the `RUN_METRIC_THRESHOLD`
    # event to determine if this is a "newer" server.
    assert fetched_a.id == fetched_b.id  # these should at least be the same

    is_older_server = not api._supports_automation(event=EventType.RUN_METRIC_THRESHOLD)
    exclude = {"id"} if is_older_server else None

    assert fetched_a.model_dump(exclude=exclude) == created.model_dump(exclude=exclude)
    assert fetched_b.model_dump(exclude=exclude) == created.model_dump(exclude=exclude)


@mark.usefixtures(reset_automations.__name__)
def test_create_existing_automation_raises_by_default_if_existing(
    api: wandb.Api,
    event,
    action,
    automation_name: str,
):
    created = api.create_automation(
        (event >> action),
        name=automation_name,
    )
    with raises(ValueError):
        api.create_automation((event >> action), name=created.name)

    # Fetching the automation by name should return the original automation,
    # unchanged.
    fetched = api.automation(name=created.name)

    # NOTE: On older server versions, the ID returned has an encoded index that's off by 1.
    # This seems fixed on newer servers.  Use RUN_METRIC_THRESHOLD support as a proxy for identifying
    # newer servers.
    is_older_server = not api._supports_automation(event=EventType.RUN_METRIC_THRESHOLD)
    exclude = {"id"} if is_older_server else None

    assert fetched.model_dump(exclude=exclude) == created.model_dump(exclude=exclude)


@mark.usefixtures(reset_automations.__name__)
def test_create_existing_automation_fetches_existing_if_requested(
    api: wandb.Api,
    event,
    action,
    automation_name: str,
):
    created = api.create_automation(
        (event >> action),
        name=automation_name,
    )

    # Since we request the prior automation if it exists, any extra values
    # that would normally be set on the created object will be ignored.
    existing = api.create_automation(
        (event >> action),
        name=created.name,
        description="ignored description",
        fetch_existing=True,
    )

    # Fetch the automation by name
    fetched = api.automation(name=created.name)

    # NOTE: On older server versions, the ID returned has an encoded index that's off by 1.
    # This seems fixed on newer servers.  Use RUN_METRIC_THRESHOLD support as a proxy for identifying
    # newer servers.
    is_older_server = not api._supports_automation(event=EventType.RUN_METRIC_THRESHOLD)
    exclude = {"id"} if is_older_server else None

    assert created.model_dump(exclude=exclude) == existing.model_dump(exclude=exclude)
    assert existing.model_dump(exclude=exclude) == fetched.model_dump(exclude=exclude)

    assert created.description is None
    assert existing.description is None
    assert fetched.description is None


@mark.usefixtures(reset_automations.__name__)
def test_create_automation_for_run_metric_threshold_event(
    project,
    webhook,
    api: wandb.Api,
    automation_name: str,
):
    expected_filter = RunMetricFilter(
        run={"$and": [{"display_name": {"$contains": "my-run"}}]},
        metric=MetricThresholdFilter(
            name="my-metric",
            window=5,
            agg="AVERAGE",
            cmp="$gt",
            threshold=0,
        ),
    )

    event = OnRunMetric(
        scope=project,
        filter=(RunEvent.metric("my-metric").mean(5) > 0)
        & RunEvent.name.contains("my-run"),
    )
    action = SendWebhook.from_integration(webhook)

    server_supports_event = api._supports_automation(event=event.event_type)

    expectation = nullcontext() if server_supports_event else raises(ValueError)

    with expectation:
        automation = api.create_automation(
            (event >> action),
            name=automation_name,
            description="longer description here",
        )

    if server_supports_event:
        assert isinstance(automation, Automation)
        assert automation.event.filter == expected_filter

        # We should be able to fetch the automation by name (optionally filtering by entity)
        entity_name = project.entity
        assert len(list(api.automations(entity=entity_name, name=automation_name))) == 1
        assert len(list(api.automations(name=automation_name))) == 1


@mark.usefixtures(reset_automations.__name__)
def test_delete_automation(api: wandb.Api, event, action, automation_name: str):
    created = api.create_automation(
        (event >> action),
        name=automation_name,
    )

    # Fetch the automation by name (avoids the off-by-1 index issue on older servers)
    fetched = api.automation(name=created.name)
    assert fetched.name in {a.name for a in api.automations()}

    api.delete_automation(fetched)
    assert fetched.name not in {a.name for a in api.automations()}


@mark.usefixtures(reset_automations.__name__)
def test_delete_automation_by_id(api: wandb.Api, event, action, automation_name: str):
    created = api.create_automation(
        (event >> action),
        name=automation_name,
    )

    # Fetch the automation by name (avoids the off-by-1 index issue on older servers)
    fetched = api.automation(name=created.name)
    assert fetched.name in {a.name for a in api.automations()}

    api.delete_automation(fetched.id)
    assert fetched.name not in {a.name for a in api.automations()}


@mark.usefixtures(reset_automations.__name__)
def test_automation_cannot_be_deleted_again(
    api: wandb.Api, event, action, automation_name: str
):
    created = api.create_automation(
        (event >> action),
        name=automation_name,
    )

    # Fetch the automation by name (avoids the off-by-1 index issue on older servers)
    fetched = api.automation(name=created.name)
    assert fetched.name in {a.name for a in api.automations()}

    api.delete_automation(fetched)
    assert fetched.name not in {a.name for a in api.automations()}

    with raises(requests.HTTPError):
        api.delete_automation(fetched)

    with raises(requests.HTTPError):
        api.delete_automation(fetched.id)


@mark.usefixtures(reset_automations.__name__)
def test_delete_automation_raises_on_invalid_id(api: wandb.Api):
    with raises(requests.HTTPError):
        api.delete_automation("invalid-automation-id")


@fixture
def skip_if_edit_automations_not_supported_on_server(api: wandb.Api):
    # HACK: Use NO_OP as a proxy for whether the server is "new enough"
    #
    # FIXME: We need a better way to check this in the absence of
    # - a prior server feature flag
    # - use of GraphQL introspection queries
    if not api._supports_automation(action=ActionType.NO_OP):
        skip("Server does not support editing automations")


@mark.usefixtures(skip_if_edit_automations_not_supported_on_server.__name__)
class TestUpdateAutomation:
    @fixture
    def old_automation(
        self,
        api: wandb.Api,
        event,
        action,
        automation_name: str,
    ):
        """The original automation to be updated."""
        # Setup: Create the original automation
        automation = api.create_automation(
            (event >> action),
            name=automation_name,
            description="original description",
        )
        yield automation

        # Cleanup: Delete the automation for good measure
        api.delete_automation(automation)
        assert len(list(api.automations(name=automation_name))) == 0

    def test_update_name(self, api: wandb.Api, old_automation: Automation):
        updated_value = "new-name"

        old_automation.name = updated_value
        new_automation = api.update_automation(old_automation)

        assert new_automation.name == updated_value

    def test_update_description(self, api: wandb.Api, old_automation: Automation):
        new_value = "new description"

        old_automation.description = new_value
        new_automation = api.update_automation(old_automation)

        assert new_automation.description == new_value

    def test_update_enabled(self, api: wandb.Api, old_automation: Automation):
        new_value = False

        old_automation.enabled = new_value
        new_automation = api.update_automation(old_automation)

        assert new_automation.enabled == new_value

    def test_update_action_to_webhook(
        self, api: wandb.Api, old_automation: Automation, webhook: WebhookIntegration
    ):
        # This is deliberately an "input" action, even though saved automations
        # will have a "saved" action on them.  We want to check that this is still
        # handled correctly and reliably.
        webhook_id = webhook.id
        new_payload = {"new-key": "new-value"}
        webhook_action = SendWebhook(
            integration_id=webhook_id,
            request_payload=new_payload,
        )

        old_automation.action = webhook_action
        new_automation = api.update_automation(old_automation)

        new_action = new_automation.action
        assert isinstance(new_action, SavedWebhookAction)
        assert new_action.action_type == ActionType.GENERIC_WEBHOOK
        assert new_action.integration.id == webhook_id
        assert new_action.request_payload == new_payload

    def test_update_action_to_no_op(self, api: wandb.Api, old_automation: Automation):
        # This is deliberately an "input" action, even though saved automations
        # will have a "saved" action on them.  We want to check that this is still
        # handled correctly and reliably.

        old_automation.action = DoNothing()
        new_automation = api.update_automation(old_automation)

        new_action = new_automation.action
        # NO_OP actions don't have meaningful fields besides these
        assert isinstance(new_action, SavedNoOpAction)
        assert new_action.action_type == ActionType.NO_OP

    # This is only meaningful if the original automation has a webhook action
    @mark.parametrize("action_type", [ActionType.GENERIC_WEBHOOK], indirect=True)
    def test_update_webhook_payload(self, api: wandb.Api, old_automation: Automation):
        new_payload = {"new-key": "new-value"}

        old_automation.action.request_payload = new_payload
        new_automation = api.update_automation(old_automation)

        assert new_automation.action.request_payload == new_payload

    # This is only meaningful if the original automation has a notification action
    @mark.parametrize("action_type", [ActionType.NOTIFICATION], indirect=True)
    def test_update_notification_message(
        self, api: wandb.Api, old_automation: Automation
    ):
        new_message = "new message"

        old_automation.action.message = new_message
        new_automation = api.update_automation(old_automation)

        assert new_automation.action.message == new_message

    def test_update_scope_to_project(
        self, api: wandb.Api, old_automation: Automation, project: Project
    ):
        old_automation.scope = project

        new_automation = api.update_automation(old_automation)
        updated_scope = new_automation.scope

        assert isinstance(updated_scope, ProjectScope)
        assert updated_scope.id == project.id
        assert updated_scope.name == project.name

    @mark.parametrize(
        # Run (metric) events don't support ArtifactCollection scope, so we'll test those separately.
        "event_type",
        sorted(
            set(EventType)
            - {EventType.RUN_METRIC_THRESHOLD, EventType.RUN_METRIC_CHANGE}
        ),
        indirect=True,
    )
    def test_update_scope_to_artifact_collection(
        self,
        api: wandb.Api,
        old_automation: Automation,
        event_type: EventType,
        artifact_collection: ArtifactCollection,
    ):
        assert old_automation.event.event_type == event_type  # Consistency check

        old_automation.scope = artifact_collection
        new_automation = api.update_automation(old_automation)

        updated_scope = new_automation.scope

        assert isinstance(updated_scope, ArtifactCollectionScopeTypes)
        assert updated_scope.id == artifact_collection.id
        assert updated_scope.name == artifact_collection.name

    @mark.parametrize(
        "event_type",
        [EventType.RUN_METRIC_THRESHOLD, EventType.RUN_METRIC_CHANGE],
        indirect=True,
    )
    def test_update_scope_to_artifact_collection_fails_for_incompatible_event(
        self,
        api: wandb.Api,
        old_automation: Automation,
        event_type: EventType,
        artifact_collection: ArtifactCollection,
    ):
        """Updating automation scope to an artifact collection fails if the event type doesn't support it."""
        assert old_automation.event.event_type == event_type  # Consistency check

        with raises(requests.HTTPError):
            old_automation.scope = artifact_collection
            api.update_automation(old_automation)

    @mark.parametrize(
        "updates",
        [
            {"name": "new-name"},
            {"description": "new-description"},
            {"enabled": False},
            {"description": "new-description", "enabled": False},
            {"name": "new-name", "enabled": False},
            {"name": "new-name", "description": "new-description", "enabled": False},
        ],
    )
    def test_update_via_kwargs(
        self,
        api: wandb.Api,
        old_automation: Automation,
        updates: dict[str, Any],
    ):
        # Update the automation
        new_automation = api.update_automation(old_automation, **updates)
        for name, value in updates.items():
            assert getattr(new_automation, name) == value


class TestPaginatedAutomations:
    @fixture(scope="class")
    def num_projects(self) -> int:
        return 10

    @fixture(scope="class", params=[1, 2, 3])
    def page_size(self, request: FixtureRequest) -> int:
        return request.param

    @fixture(scope="class")
    def num_pages(self, num_projects: int, page_size: int) -> int:
        """The number of pages we'll expect to encounter via paginated requests."""
        # NOTE: For now, pagination is per project, NOT per automation
        return math.ceil(num_projects / page_size)

    @fixture(scope="class")
    def setup_paginated_automations(
        self,
        user: str,
        api: wandb.Api,
        webhook: WebhookIntegration,
        num_projects: int,
        make_name: Callable[[str], str],
    ):
        # HACK: Is there a way to ensure a clean slate for each test?
        for id_ in api.automations():
            api.delete_automation(id_)

        # NOTE: For now, pagination is per project, NOT per automation, so
        # to test pagination, we'll create each automation in a separate project.
        #
        # UPDATE THIS in the future if we switch to per-automation pagination.
        project_names = [make_name(f"project-{i}") for i in range(num_projects)]
        automation_names = [make_name(f"automation-{i}") for i in range(num_projects)]

        created_automation_ids = deque()
        for project_name, automation_name in zip(project_names, automation_names):
            # Create the placeholder project for the automation
            api.create_project(name=project_name, entity=user)
            project = api.project(name=project_name, entity=user)

            # Create the actual automation
            created = api.create_automation(
                OnLinkArtifact(scope=project) >> SendWebhook.from_integration(webhook),
                name=automation_name,
                description="longer description here",
            )

            # Refetch (to avoid the off-by-1 index issue on older servers) and retain for later cleanup
            refetched_id = api.automation(name=created.name).id
            created_automation_ids.append(refetched_id)

        yield

        # This particular fixture is deliberately class-scoped, but clean up the automations for good measure
        for id_ in created_automation_ids:
            api.delete_automation(id_)

    @mark.usefixtures(setup_paginated_automations.__name__)
    def test_paginated_automations(
        self,
        mocker,
        user,
        api: wandb.Api,
        num_projects,
        page_size,
    ):
        # Spy on the client method that makes the GQL request.  Not ideal, but it may have to do for now
        client_spy = mocker.spy(api.client, "execute")

        # Fetch the automations
        list(api.automations(entity=user, per_page=page_size))

        # Check that the number of GQL requests is at least what we expect from the pagination params
        # Note that a (cached) introspection query may add an extra request the first time this is
        # called.
        expected_page_count = math.ceil(num_projects / page_size)

        assert client_spy.call_count >= expected_page_count
