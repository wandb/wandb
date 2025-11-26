from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

import wandb
from pytest import fixture, mark
from test.support import SHORT_TIMEOUT, sleeping_retry
from wandb import Artifact
from wandb.apis.public import ArtifactCollection, Project
from wandb.automations import Automation, DoNothing
from wandb.automations._generated.enums import TriggerExecutionState
from wandb.automations.actions import ActionType
from wandb.automations.events import EventType
from wandb.automations.scopes import ScopeType


@fixture
def automation(
    api: wandb.Api,
    event: Any,
    make_name: Callable[[str], str],
) -> Iterator[Automation]:
    """An already-created automation for testing history.

    Uses DoNothing action to avoid making external requests during tests.
    """
    action = DoNothing()
    created = api.create_automation(
        (event >> action),
        name=make_name("test-automation-history"),
    )

    # Fetch by name to ensure correct ID on older servers
    fetched = api.automation(name=created.name)

    yield fetched

    # Cleanup
    api.delete_automation(fetched)


# ----------------------------------------------------------------------------
# Tests for automation.history()
# ----------------------------------------------------------------------------


def test_automation_history_returns_iterable(automation: Automation):
    """Test that automation.history() returns an iterable and is sized."""
    history = automation.history()

    # Should support len() - ExecutedAutomations is a SizedRelayPaginator
    assert len(history) >= 0  # Will raise if not Sized


def test_automation_history_empty_when_no_executions(
    automation: Automation,
    artifact_collection: ArtifactCollection,
    project: Project,
):
    """Test that automation history is empty when no executions exist.

    This test hits the real server, which should return no executions for a
    newly-created automation that has never been triggered.
    """
    assert len(automation.history()) == 0
    assert len(artifact_collection.automation_history()) == 0
    assert len(project.automation_history()) == 0


@mark.skip(reason="TODO: Fix this test")
@mark.parametrize("scope_type", [ScopeType.PROJECT], indirect=True)
@mark.parametrize("event_type", [EventType.RUN_METRIC_THRESHOLD], indirect=True)
def test_automation_history_records_execution_for_project_scope(
    artifact: Artifact,
    automation: Automation,
    scope: Project,
    make_name: Callable[[str], str],
    api: wandb.Api,
):
    """Test that triggering an automation creates execution history.

    For project scope, we link an artifact which should trigger the OnLinkArtifact event.
    """
    # Consistency/sanity checks
    assert isinstance(scope, Project)
    project = scope  # For clarity
    assert automation.scope.scope_type is ScopeType.PROJECT
    assert automation.scope.id == project.id

    # Verify empty history before triggering
    assert len(automation.history()) == 0
    assert len(project.automation_history()) == 0

    # Trigger the automation by linking an artifact in the project
    # artifact = Artifact(name=make_name("test-artifact"), type="dataset")
    with wandb.init(entity=project.entity, project=project.name) as run:
        for i in range(10):
            # Ensure the logged metric is above the threshold
            run.log({"my-metric": 10 + i * 0.1})
        # reused_artifact = run.use_artifact(artifact)
        # reused_artifact.wait()

        # linked_artifact = run.link_artifact(
        #     reused_artifact,
        #     f"{project.entity}/{project.name}/linked-collection",
        # )
        # linked_artifact.wait()

        # refetched_linked_artifact = api.artifact(linked_artifact.qualified_name)
        # assert refetched_linked_artifact.is_link
        # assert refetched_linked_artifact.project == project.name

    # artifact.wait()
    # artifact.link(f"{project.entity}/{project.name}/linked-collection")

    # It might take a moment for the server to execute, so we're ok
    # retrying, within a reasonable timeout.
    for _ in sleeping_retry(
        SHORT_TIMEOUT,
        "Timeout waiting on server for evidence of automation history",
    ):
        if len(project.automation_history()) > 0:
            break

    # Fetch execution history - should show at least one execution
    executions = list(automation.history())
    project_executions = list(project.automation_history())
    assert len(executions) == len(project_executions) == 1

    # Verify the execution has expected properties
    execution = executions[0]
    assert execution.automation_id == automation.id
    assert execution.automation_name == automation.name
    assert execution.triggered_at is not None
    assert execution.event is not None
    assert execution.event.event_type is EventType.LINK_ARTIFACT
    assert execution.action is not None
    assert execution.action.action_type is ActionType.NO_OP
    assert execution.state is TriggerExecutionState.FINISHED


# TODO: FIX THIS TEST
@mark.parametrize("scope_type", [ScopeType.ARTIFACT_COLLECTION], indirect=True)
@mark.parametrize("event_type", [EventType.CREATE_ARTIFACT], indirect=True)
def test_automation_history_records_execution_for_collection_scope(
    artifact: Artifact,
    scope: ArtifactCollection,
    automation: Automation,
    tmp_path: Path,
    make_name: Callable[[str], str],
):
    """Test that triggering an automation creates execution history.

    For artifact collection scope, we create a new artifact version which should
    trigger the OnCreateArtifact event.
    """
    # Consistency/sanity checks
    assert isinstance(collection := scope, ArtifactCollection)
    collection = scope  # For clarity

    # Verify empty history before triggering
    assert len(collection.automation_history()) == 0
    assert len(automation.history()) == 0

    # Trigger the automation by logging new versions of the original source artifact
    with wandb.init(entity=collection.entity, project=collection.project) as run:
        reused_artifact = run.use_artifact(artifact)

        new_version = reused_artifact.new_draft()

        tmp_fpath = tmp_path / f"{make_name('placeholder')}.txt"
        tmp_fpath.write_text(f"placeholder-{uuid4()!s}")

        new_version.add_file(str(tmp_fpath))
        logged_new_version = run.log_artifact(new_version)

        logged_new_version.wait()

    # FIXME: Is there a more reliable way to wait for the server without blocking other tests?
    # It might take a moment for the server to execute, so we may need to
    # retrying, within a reasonable timeout.
    for _ in sleeping_retry(
        SHORT_TIMEOUT,
        "Timeout waiting on server for evidence of automation history",
    ):
        if len(list(collection.automation_history())) > 0:
            break

    # Fetch execution history - should show at least one execution
    executions = list(automation.history())
    collection_executions = list(collection.automation_history())
    assert len(collection_executions) == len(executions) == 1

    # Verify the execution has expected properties
    execution = executions[0]
    assert execution.automation_id == automation.id
    assert execution.automation_name == automation.name
    assert execution.triggered_at is not None
    assert execution.state == TriggerExecutionState.FINISHED
