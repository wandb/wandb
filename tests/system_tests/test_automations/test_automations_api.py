from __future__ import annotations

from collections import deque

import wandb
from pytest import fixture, raises
from wandb import Artifact
from wandb.apis import public
from wandb.sdk.automations import Automation
from wandb.sdk.automations._generated.fragments import WebhookIntegration
from wandb.sdk.automations.actions import DoWebhook
from wandb.sdk.automations.events import (
    MetricFilter,
    OnCreateArtifact,
    OnRunMetric,
    RunEvent,
    RunFilter,
    RunMetricFilter,
)
from wandb.sdk.automations.filters._expressions import FilterExpr


@fixture
def project_name() -> str:
    """Name for a test Project."""
    return "test-project"


@fixture
def artifact(user, project_name, api: wandb.Api) -> Artifact:
    with wandb.init(entity=user, project=project_name) as run:
        artifact = Artifact("test-artifact", "dataset")
        logged_artifact = run.log_artifact(artifact)
    return logged_artifact.wait()


@fixture
def artifact_collection(artifact, api: wandb.Api) -> public.ArtifactCollection:
    """A test ArtifactCollection for tests in this module."""
    return api.artifact(name=artifact.qualified_name, type=artifact.type).collection


@fixture
def project(user, project_name, api: wandb.Api) -> public.Project:
    """A test Project for tests in this module."""

    # Create the project first if it doesn't exist yet
    api.create_project(name=project_name, entity=user)
    return api.project(name=project_name, entity=user)


@fixture  # (scope="session")
def webhook_integration(user: str) -> WebhookIntegration:
    from wandb_gql import gql

    # HACK: Need to instantiate separately here since the `api` fixture is function-scoped
    api = wandb.Api()

    # HACK: Set up a placeholder webhook integration and return it

    # At the time of testing/implementation, this is the action with
    # the lowest setup overhead and, if needed, probably least difficult
    # to patch/mock/stub/spy/intercept
    gql_mutation = gql(
        """
        mutation CreateGenericWebhookIntegration(
            $entityName: String!,
            $url: String!,
            $name: String!,
        ) {
            createGenericWebhookIntegration(
                input: {
                    entityName: $entityName,
                    urlEndpoint: $url,
                    name: $name,
                }
            ) {
                integration {
                    __typename
                    ... on GenericWebhookIntegration {
                        id
                        name
                        urlEndpoint
                        createdAt
                    }
                }
            }
        }
        """
    )
    data = api.client.execute(
        gql_mutation,
        variable_values={
            "entityName": user,
            "url": "test-url",
            "name": "my-webhook",
        },
    )
    integration_data = data["createGenericWebhookIntegration"]["integration"]

    # Consistency check: the integration should be there now
    assert len(list(api.integrations(kind="webhook"))) == 1

    return WebhookIntegration.model_validate(integration_data)


# ------------------------------------------------------------------------------
def test_no_initial_automations(user, api: wandb.Api):
    """No automations should be fetched by the API prior to creating any."""
    assert list(api.automations()) == []


def test_no_initial_integrations(user, api: wandb.Api):
    """No automations should be fetched by the API prior to creating any."""
    assert list(api.integrations(kind="slack")) == []
    assert list(api.integrations(kind="webhook")) == []


def test_no_initial_slack_integration(user, api: wandb.Api):
    with raises(ValueError, match="No Slack integration found"):
        _ = list(api.slack_integration(user))


def test_new_create_artifact_automation(
    request, artifact_collection, webhook_integration, api: wandb.Api
):
    # To ensure uniqueness, name the automation the fully qualified name of the current test
    automation_name = request.node.name

    event = OnCreateArtifact(
        scope=artifact_collection,
    )
    action = DoWebhook(
        integration_id=webhook_integration.id,
        request_payload={},
    )

    automation = api.create_automation(
        (event >> action),
        name=automation_name,
        description="longer description here",
    )

    # TODO: Go beyond smoke tests
    assert isinstance(automation, Automation)

    # We should be able to fetch the automation by name (optionally filtering by entity)
    entity_name = artifact_collection.entity
    assert len(list(api.automations(entity=entity_name, name=automation_name))) == 1
    assert len(list(api.automations(name=automation_name))) == 1

    # Delete the automation for good measure
    api.delete_automation(automation)
    assert len(list(api.automations(entity=entity_name, name=automation_name))) == 0
    assert len(list(api.automations(name=automation_name))) == 0


def test_new_run_metric_automation(request, project, webhook_integration, api):
    # To ensure uniqueness, name the automation the fully qualified name of the current test
    automation_name = request.node.name

    expected_filter = RunMetricFilter(
        run_filter=RunFilter(
            other=[FilterExpr.model_validate({"display_name": {"$contains": "my-run"}})]
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
    assert len(list(api.automations(entity=entity_name, name=automation_name))) == 0
    assert len(list(api.automations(name=automation_name))) == 0


class TestPaginatedAutomations:
    @fixture
    def total_projects(self) -> int:
        return 10

    @fixture
    def setup_paginated_automations(
        self,
        user: str,
        api: wandb.Api,
        webhook_integration: WebhookIntegration,
        total_projects: int,
    ):
        # NOTE: For the moment, pagination is per project, NOT per automation, so
        # create a project for each automation.
        automations = deque()
        for i in range(total_projects):
            project_name = f"project-{i}"
            api.create_project(name=project_name, entity=user)
            project = api.project(name=project_name, entity=user)

            event = OnCreateArtifact(
                scope=project,
            )
            action = DoWebhook(
                integration_id=webhook_integration.id,
                request_payload={},
            )
            automation = api.create_automation(
                (event >> action),
                name=f"automation-{i}",
                description="longer description here",
            )
            automations.append(automation)

        yield

        # Delete the automations for good measure
        for automation in automations:
            api.delete_automation(automation)

    def test_paginated_automations(
        self,
        mocker,
        user,
        api: wandb.Api,
        setup_paginated_automations,
        total_projects,
    ):
        # NOTE: For the moment, pagination is per project, NOT per automation.
        # Will need to update what we check for in this test if we switch to per-automation pagination.
        per_page = 1

        # FIXME: Find a better (client-agnostic) way to spy on the number of GQL requests
        client_spy = mocker.spy(api.client, "execute")

        # Fetch the automations
        automations = list(api.automations(per_page=per_page))

        # Check that the number of GQL requests is what's expected from the pagination params

        # FIXME: Fix the race condition here so we can assert on the exact number of automations/requests
        # assert len(automations) == total_projects
        # assert client_spy.call_count == total_projects // per_page + 1
        assert len(automations) >= total_projects
        assert client_spy.call_count >= total_projects // per_page + 1
