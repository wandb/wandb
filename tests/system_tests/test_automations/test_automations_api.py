from pytest import fixture, raises
from wandb import Artifact
from wandb.apis import public
from wandb.sdk.automations import Automation
from wandb.sdk.automations._filters.filter import FilterExpression
from wandb.sdk.automations._filters.logic import And
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
def collection_name() -> str:
    """Name for a test ArtifactCollection."""
    return "test-collection"


@fixture
def project_name() -> str:
    """Name for a test Project."""
    return "test-project"


@fixture
def artifact(user, wandb_init, project_name, collection_name, api) -> Artifact:
    with wandb_init(entity=user, project=project_name) as run:
        artifact = Artifact("test-artifact", "dataset")
        logged_artifact = run.log_artifact(artifact)

    return logged_artifact.wait()


@fixture
def artifact_collection(
    project_name,
    collection_name,
    artifact,
    api,
) -> public.ArtifactCollection:
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
        f"""
        mutation CreateGenericWebhookIntegration {{
            createGenericWebhookIntegration(
                input: {{
                    entityName: "{user}",
                    urlEndpoint: "test-url",
                    name: "my-webhook",
                }}
            ) {{
                integration {{
                    id
                }}
            }}
        }}
        """
    )
    data = api.client.execute(gql_mutation)
    return data["createGenericWebhookIntegration"]["integration"]["id"]


# ------------------------------------------------------------------------------
def test_no_initial_automations(user, api):
    """No automations should be fetched by the API prior to creating any."""
    assert list(api.automations()) == []


def test_no_initial_slack_integrations(user, api):
    with raises(ValueError, match="No Slack integration found"):
        _ = list(api._team_slack_integration(user))

    with raises(ValueError, match="No Slack integration found"):
        _ = list(api._user_slack_integration())


def test_new_create_artifact_automation(
    artifact_collection, webhook_integration_id, api
):
    event = OnCreateArtifact(
        scope=artifact_collection,
    )
    action = DoWebhook(
        integration_id=webhook_integration_id,
        request_payload={},
    )

    new_automation = api.create_automation(
        (event >> action),
        name="Testing programmatic automations API",
        description="longer description here",
    )

    # TODO: Go beyond smoke tests
    assert isinstance(new_automation, Automation)


def test_new_run_metric_automation(project, webhook_integration_id, api):
    expected_filter = RunMetricFilter(
        run_filter=RunFilter.model_validate(
            And(
                inner_operand=[
                    FilterExpression.model_validate(
                        {"display_name": {"$contains": "my-run"}}
                    )
                ]
            )
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
        name="Testing programmatic automations API",
        description="longer description here",
    )

    assert isinstance(automation, Automation)
    assert automation.event.filter == expected_filter
