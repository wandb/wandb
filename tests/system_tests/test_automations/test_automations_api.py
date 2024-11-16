from __future__ import annotations

import math
from collections import deque
from typing import Callable

import requests
import wandb
from pytest import fixture, raises, xfail
from wandb.apis.public.integrations import WebhookIntegration
from wandb.sdk.automations import Automation, DoWebhook, OnCreateArtifact, OnRunMetric
from wandb.sdk.automations.events import MetricFilter, RunEvent, RunMetricFilter
from wandb.sdk.automations.filters import And


@fixture
def automation_name(make_name: Callable[[str], str]) -> str:
    return make_name("test-automation")


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
    assert api.automation(entity=user, name=automation.name) == automation
    assert api.automation(name=automation.name) == automation

    # Delete the automation for good measure
    api.delete_automation(automation)
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
    assert api.automation(entity=user, name=automation.name) == automation
    assert api.automation(name=automation.name) == automation

    # Delete the automation for good measure
    api.delete_automation(automation)
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
    with raises(requests.HTTPError):
        _ = api.create_automation((event >> action), name=automation.name)

    # Fetching the automation by name should return the original automation,
    # unchanged.
    assert api.automation(name=automation.name) == automation


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

    assert automation1 == automation2
    assert automation2 == automation3
    assert automation1.description is None


def test_create_automation_for_run_metric_event(
    project,
    webhook_integration,
    api,
    automation_name: str,
    server_supported_automation_types,
):
    expected_filter = RunMetricFilter(
        run_filter=And(
            inner=[{"display_name": {"$contains": "my-run"}}],
        ),
        metric_filter=MetricFilter(
            name="my-metric",
            window_size=5,
            agg_op="AVERAGE",
            cmp_op="$gt",
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

    if event.event_type.value not in server_supported_automation_types.event_types:
        xfail(f"Server does not support event type: {event.event_type.value!r}")

    automation = api.create_automation(
        (event >> action),
        name=automation_name,
        description="longer description here",
    )

    assert isinstance(automation, Automation)
    assert automation.event.filter == expected_filter

    # We should be able to fetch the automation by name (optionally filtering by entity)
    entity_name = project.entity
    assert len(list(api.automations(entity=entity_name, name=automation_name))) == 1
    assert len(list(api.automations(name=automation_name))) == 1

    # Delete the automation for good measure
    api.delete_automation(automation)
    assert len(list(api.automations(name=automation_name))) == 0


class TestPaginatedAutomations:
    @fixture(scope="class")
    def total_projects(self) -> int:
        return 10

    @fixture(scope="class")
    def page_size(self) -> int:
        return 1

    @fixture(scope="class")
    def paginated_automations(
        self,
        user: str,
        api: wandb.Api,
        make_webhook_integration: Callable[[str, str, str], WebhookIntegration],
        total_projects: int,
        make_name: Callable[[str], str],
    ):
        # HACK: Is there a way to ensure a clean slate for each test?
        if existing_automations := list(api.automations()):
            for automation in existing_automations:
                api.delete_automation(automation)

        webhook_integration = make_webhook_integration(
            "test-webhook", user, "fake-webhook-url"
        )

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
            event = OnCreateArtifact(
                scope=project,
            )
            action = DoWebhook.from_integration(webhook_integration, payload={})
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
            api.delete_automation(automation)

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

        # Check that the number of GQL requests is what's expected from the pagination params
        expected_introspection_count = 1
        expected_page_count = math.ceil(total_projects / page_size)
        expected_total_count = expected_introspection_count + expected_page_count

        assert client_spy.call_count == expected_total_count
