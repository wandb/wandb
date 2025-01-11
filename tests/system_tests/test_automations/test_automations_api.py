from __future__ import annotations

import math
from collections import deque
from contextlib import nullcontext
from typing import Any, Callable

import wandb
from pytest import FixtureRequest, fixture, mark, raises
from wandb.apis.public import ArtifactCollection, Project
from wandb.automations import (
    ActionType,
    Automation,
    DoWebhook,
    EventType,
    OnLinkArtifact,
    OnRunMetric,
    ProjectScope,
    WebhookIntegration,
)
from wandb.automations.events import MetricThresholdFilter, RunEvent, RunMetricFilter
from wandb.automations.scopes import ArtifactCollectionScopeTypes


@fixture
def automation_name(make_name: Callable[[str], str]) -> str:
    return make_name(prefix="test-automation")


# ------------------------------------------------------------------------------
def test_no_initial_automations(api: wandb.Api, clear_initial_automations):
    """No automations should be fetched by the API prior to creating any."""
    assert list(api.automations()) == []


def test_no_initial_integrations(user, api: wandb.Api):
    """No automations should be fetched by the API prior to creating any."""
    assert list(api.integrations()) == []
    assert list(api.slack_integrations()) == []
    assert list(api.webhook_integrations()) == []


def test_create_automation_via_api(
    user: str,
    api: wandb.Api,
    event,
    action,
    automation_name: str,
):
    automation = api.create_automation(
        (event >> action),
        name=automation_name,
        description="test-description",
    )

    # We should be able to fetch the automation by name (optionally filtering by entity)
    assert automation.name == automation_name

    refetched_a = api.automation(entity=user, name=automation.name)
    refetched_b = api.automation(name=automation.name)

    # NOTE: On older server versions, the ID returned returned by create_automation()
    # seems to have an (encoded) index that's off by 1, vs. the ID returned by
    # automation().
    # This seems fixed on newer servers.  Use server support for the `RUN_METRIC`
    # event to determine if this is a "newer" server.

    assert refetched_a.id == refetched_b.id  # these should at least be the same

    is_older_server = not api._supports_automation(event=EventType.RUN_METRIC)
    if is_older_server:
        dump_kws = {"exclude": {"id"}}
        assert refetched_a.model_dump(**dump_kws) == automation.model_dump(**dump_kws)
        assert refetched_b.model_dump(**dump_kws) == automation.model_dump(**dump_kws)
    else:
        assert refetched_a.model_dump() == automation.model_dump()
        assert refetched_b.model_dump() == automation.model_dump()

    # Delete the automation for good measure
    api.delete_automation(api.automation(name=automation.name))
    assert len(list(api.automations(name=automation.name))) == 0


def test_create_automation_via_save(
    user: str,
    api: wandb.Api,
    event,
    action,
    automation_name: str,
):
    automation = (event >> action).save(
        name=automation_name,
        description="test-description",
    )

    # We should be able to fetch the automation by name (optionally filtering by entity)
    assert automation.name == automation_name

    refetched_a = api.automation(entity=user, name=automation.name)
    refetched_b = api.automation(name=automation.name)

    # NOTE: On older server versions, the ID returned returned by create_automation()
    # seems to have an (encoded) index that's off by 1, vs. the ID returned by
    # automation().
    # This seems fixed on newer servers.  Use server support for the `RUN_METRIC`
    # event to determine if this is a "newer" server.

    assert refetched_a.id == refetched_b.id  # these should at least be the same

    is_older_server = not api._supports_automation(event=EventType.RUN_METRIC)
    if is_older_server:
        dump_kws = {"exclude": {"id"}}
        assert refetched_a.model_dump(**dump_kws) == automation.model_dump(**dump_kws)
        assert refetched_b.model_dump(**dump_kws) == automation.model_dump(**dump_kws)
    else:
        assert refetched_a.model_dump() == automation.model_dump()
        assert refetched_b.model_dump() == automation.model_dump()

    # Delete the automation for good measure
    api.delete_automation(api.automation(name=automation.name))
    assert len(list(api.automations(name=automation.name))) == 0


def test_create_existing_automation_raises_by_default(
    api: wandb.Api,
    event,
    action,
    automation_name: str,
):
    automation = api.create_automation(
        (event >> action),
        name=automation_name,
    )
    with raises(ValueError):
        api.create_automation((event >> action), name=automation_name)

    # Fetching the automation by name should return the original automation,
    # unchanged.
    refetched = api.automation(name=automation.name)

    # NOTE: On older server versions, the ID returned has an encoded index that's off by 1.
    # This seems fixed on newer servers.  Use RUN_METRIC support as a proxy for identifying
    # newer servers.
    is_older_server = not api._supports_automation(event=EventType.RUN_METRIC)
    if is_older_server:
        dump_kws = {"exclude": {"id"}}
        assert refetched.model_dump(**dump_kws) == automation.model_dump(**dump_kws)
    else:
        assert refetched.model_dump() == automation.model_dump()


def test_create_existing_automation_fetches_existing_if_requested(
    api: wandb.Api,
    event,
    action,
    automation_name: str,
):
    automation1 = api.create_automation(
        (event >> action),
        name=automation_name,
    )
    automation2 = api.create_automation(
        (event >> action),
        name=automation_name,
        description="ignored description",
        fetch_existing=True,
    )

    # Fetch the automation by name
    automation3 = api.automation(name=automation_name)

    # NOTE: On older server versions, the ID returned has an encoded index that's off by 1.
    # This seems fixed on newer servers.  Use RUN_METRIC support as a proxy for identifying
    # newer servers.
    is_older_server = not api._supports_automation(event=EventType.RUN_METRIC)
    if is_older_server:
        dump_kws = {"exclude": {"id"}}
        assert automation1.model_dump(**dump_kws) == automation2.model_dump(**dump_kws)
        assert automation2.model_dump(**dump_kws) == automation3.model_dump(**dump_kws)
    else:
        assert automation1.model_dump() == automation2.model_dump()
        assert automation2.model_dump() == automation3.model_dump()
    assert automation1.description is None


def test_create_automation_for_run_metric_event(
    project,
    webhook_integration,
    api: wandb.Api,
    automation_name: str,
):
    expected_filter = RunMetricFilter(
        run_filter={"$and": [{"display_name": {"$contains": "my-run"}}]},
        run_metric_filter=MetricThresholdFilter(
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
        & (RunEvent.name.contains("my-run")),
    )
    action = DoWebhook(
        integration_id=webhook_integration.id,
        request_payload={},
    )

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

        # Delete the automation for good measure
        api.delete_automation(api.automation(name=automation_name))
        assert len(list(api.automations(name=automation_name))) == 0


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

    def test_update_scope_to_artifact_collection(
        self,
        api: wandb.Api,
        old_automation: Automation,
        event_type: EventType,
        artifact_collection: ArtifactCollection,
    ):
        from contextlib import nullcontext as does_not_raise

        # RUN_METRIC doesn't support ArtifactCollection scope, so expect that to fail.
        # Otherwise, expect the update to succeed.
        if event_type is EventType.RUN_METRIC:
            expectation = raises(Exception)
        else:
            expectation = does_not_raise()

        old_automation.scope = artifact_collection

        with expectation as exc_info:
            new_automation = api.update_automation(old_automation)

        if exc_info is None:
            updated_scope = new_automation.scope

            assert isinstance(updated_scope, ArtifactCollectionScopeTypes)
            assert updated_scope.id == artifact_collection.id
            assert updated_scope.name == artifact_collection.name

    @mark.parametrize(
        "updates",
        [
            {
                "name": "new-name",
            },
            {
                "description": "new-description",
            },
            {
                "enabled": False,
            },
            {
                "description": "new-description",
                "enabled": False,
            },
            {
                "name": "new-name",
                "enabled": False,
            },
            {
                "name": "new-name",
                "description": "new-description",
                "enabled": False,
            },
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
    def total_projects(self) -> int:
        return 10

    @fixture(scope="class", params=[1, 2, 3])
    def page_size(self, request: FixtureRequest) -> int:
        return request.param

    @fixture(scope="class")
    def webhook_integration(
        self,
        make_webhook_integration: Callable[[str, str, str], WebhookIntegration],
        make_name: Callable[[str], str],
        user: str,
    ) -> WebhookIntegration:
        return make_webhook_integration(
            make_name("test-webhook"), user, "fake-webhook-url"
        )

    @fixture(scope="class")
    def paginated_automations(
        self,
        user: str,
        api: wandb.Api,
        webhook_integration: WebhookIntegration,
        total_projects: int,
        make_name: Callable[[str], str],
    ):
        # HACK: Is there a way to ensure a clean slate for each test?
        if existing_automations := list(api.automations()):
            for automation in existing_automations:
                api.delete_automation(automation)

        # NOTE: For now, pagination is per project, NOT per automation, so
        # to test pagination, we'll create each automation in a separate project.
        #
        # UPDATE THIS in the future if we switch to per-automation pagination.
        automations = deque()
        for i in range(total_projects):
            # Create the placeholder project for the automation
            project_name = make_name(f"paginated-project-{i}")
            api.create_project(name=project_name, entity=user)
            project = api.project(name=project_name, entity=user)

            # Create the actual automation
            event = OnLinkArtifact(
                scope=project,
            )
            action = DoWebhook.from_integration(webhook_integration, request_payload={})
            automation = api.create_automation(
                (event >> action),
                name=make_name(f"automation-{i}"),
                description="longer description here",
            )

            # Retain for later cleanup
            automations.append(automation)

        yield list(automations)

        # This particular fixture is deliberately class-scoped, but clean up the automations for good measure
        for automation in automations:
            api.delete_automation(api.automation(name=automation.name))

    def test_paginated_automations(
        self,
        mocker,
        user,
        api: wandb.Api,
        paginated_automations,
        total_projects,
        page_size,
    ):
        # Spy on the client method that makes the GQL request.  Not ideal, but it may have to do for now
        client_spy = mocker.spy(api.client, "execute")

        # Fetch the automations
        _ = list(api.automations(entity=user, per_page=page_size))

        # Check that the number of GQL requests is at least what we expect from the pagination params
        # Note that a (cached) introspection query may add an extra request the first time this is
        # called.
        expected_page_count = math.ceil(total_projects / page_size)

        assert client_spy.call_count >= expected_page_count
