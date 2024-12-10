from __future__ import annotations

from pytest import fixture, mark, raises
from wandb import Artifact
from wandb.apis import public
from wandb.sdk.automations import Automation
from wandb.sdk.automations._filters.filter import FilterExpr
from wandb.sdk.automations.actions import DoWebhook
from wandb.sdk.automations.events import (
    MetricFilter,
    OnCreateArtifact,
    OnRunMetric,
    RunEvent,
    RunFilter,
    RunMetricFilter,
)
from wandb_gql import gql


@fixture
def project_name() -> str:
    """Name for a test Project."""
    return "test-project"


@fixture
def artifact(user, wandb_init, project_name, api) -> Artifact:
    with wandb_init(entity=user, project=project_name) as run:
        artifact = Artifact("test-artifact", "dataset")
        logged_artifact = run.log_artifact(artifact)

    return logged_artifact.wait()


@fixture
def artifact_collection(artifact, api) -> public.ArtifactCollection:
    """A test ArtifactCollection for tests in this module."""
    return api.artifact(name=artifact.qualified_name, type=artifact.type).collection


@fixture
def project(user, wandb_init, project_name, api) -> public.Project:
    """A test Project for tests in this module."""

    # Create the project first if it doesn't exist yet
    api.create_project(name=project_name, entity=user)
    return api.project(name=project_name, entity=user)


@fixture
def webhook_integration_id(user, wandb_init, api) -> str:
    # HACK: Set up a placeholder webhook integration and return its ID

    # At the time of testing/implementation, this is the action with
    # the lowest setup overhead and, if needed, probably least difficult
    # to patch/mock/stub/spy/intercept
    gql_mutation = gql(
        """
        mutation CreateGenericWebhookIntegration($entityName: String!) {
            createGenericWebhookIntegration(
                input: {
                    entityName: $entityName,
                    urlEndpoint: "test-url",
                    name: "my-webhook",
                }
            ) {
                integration {
                    id
                }
            }
        }
        """
    )
    data = api.client.execute(gql_mutation, variable_values={"entityName": user})
    return data["createGenericWebhookIntegration"]["integration"]["id"]


# @fixture(
#     params=[
#         EventTriggeringConditionType.CREATE_ARTIFACT,
#         EventTriggeringConditionType.LINK_MODEL,
#         EventTriggeringConditionType.RUN_METRIC,
#     ],
#     ids=lambda e: e.value,
# )
# def event_type(request) -> EventTriggeringConditionType:
#     return request.param
#
#
# @fixture
# def trigger_event(
#     event_type, artifact_collection
# ) -> OnLinkArtifact | OnCreateArtifact | OnRunMetric:
#     if event_type is EventTriggeringConditionType.CREATE_ARTIFACT:
#         return OnCreateArtifact(
#             scope=artifact_collection,
#         )
#     if event_type is EventTriggeringConditionType.RUN_METRIC:
#         return RunMetricFilter()
#     # TODO: finish
#     raise ValueError(f"Unhandled event type: {event_type!r}")


# ------------------------------------------------------------------------------
def test_no_initial_automations(user, api):
    """No automations should be fetched by the API prior to creating any."""
    assert list(api.automations()) == []


def test_no_initial_slack_integration(user, api):
    with raises(ValueError, match="No Slack integration found"):
        _ = list(api.slack_integration(user))


def test_new_create_artifact_automation(
    request, artifact_collection, webhook_integration_id, api
):
    # To ensure uniqueness, name the automation the fully qualified name of the current test
    automation_name = request.node.name

    event = OnCreateArtifact(
        scope=artifact_collection,
    )
    action = DoWebhook(
        integration_id=webhook_integration_id,
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
    assert len(api.automations(entity=entity_name, name=automation_name)) == 1
    assert len(api.automations(name=automation_name)) == 1

    # Delete the automation for good measure
    api.delete_automation(automation)
    assert len(api.automations(entity=entity_name, name=automation_name)) == 0
    assert len(api.automations(name=automation_name)) == 0


def test_new_run_metric_automation(request, project, webhook_integration_id, api):
    # To ensure uniqueness, name the automation the fully qualified name of the current test
    automation_name = request.node.name

    expected_filter = RunMetricFilter(
        run_filter=RunFilter(
            other=[FilterExpr({"display_name": {"$contains": "my-run"}})]
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
        integration_id=webhook_integration_id,
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
    assert len(api.automations(entity=entity_name, name=automation_name)) == 1
    assert len(api.automations(name=automation_name)) == 1

    # Delete the automation for good measure
    api.delete_automation(automation)
    assert len(api.automations(entity=entity_name, name=automation_name)) == 0
    assert len(api.automations(name=automation_name)) == 0


@mark.xfail(
    reason="Not yet implemented",
    strict=True,
    run=False,
)
def test_paginated_automations():
    raise NotImplementedError
