from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

import wandb
from pytest import fixture, mark
from wandb import Artifact
from wandb.apis.public import ArtifactCollection, Project
from wandb.automations import Automation, DoNothing, OnCreateArtifact, OnLinkArtifact
from wandb.automations._generated.enums import TriggerExecutionState
from wandb.automations.actions import ActionType
from wandb.automations.events import EventType
from wandb.automations.scopes import ScopeType


@fixture
def automation_name(make_name: Callable[[str], str]) -> str:
    return make_name("test-automation-history")


@fixture
def automation(
    api: wandb.Api,
    event: Any,
    automation_name: str,
) -> Iterator[Automation]:
    """An already-created automation for testing history.

    Uses DoNothing action to avoid making external requests during tests.
    """
    action = DoNothing()
    created = api.create_automation((event >> action), name=automation_name)

    # Fetch by name to ensure correct ID
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


def test_automation_history_empty_when_no_executions(automation: Automation):
    """Test that automation history is empty when no executions exist.

    This test hits the real server, which should return no executions for a
    newly-created automation that has never been triggered.
    """
    assert len(automation.history()) == 0


def test_automation_history_respects_per_page_parameter(
    automation: Automation,
):
    """Test that per_page parameter is accepted."""
    # Verify the parameter is accepted and returns valid (possibly empty) results
    history = list(automation.history(per_page=10))
    # History is empty since automation hasn't been triggered
    assert history == []


# TODO: FIX THIS TEST
@mark.parametrize("scope_type", [ScopeType.PROJECT], indirect=True)
@mark.parametrize("event_type", [EventType.LINK_ARTIFACT], indirect=True)
def test_automation_history_records_execution_for_project_scope(
    automation: Automation,
    scope: Project,
    make_name: Callable[[str], str],
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
    artifact = Artifact(name=make_name("test-artifact"), type="dataset")
    with wandb.init(entity=project.entity, project=project.name) as run:
        run.log_artifact(artifact)

    artifact.wait()
    artifact.link(f"{project.entity}/{project.name}/linked-collection")

    # It might take a moment to execute, so we'll retry, within reason
    # for _ in sleeping_retry(LOOPBACK_TIMEOUT):
    #     if len(automation.history()) > 0:
    #         break

    time.sleep(5)

    # Fetch execution history - should show at least one execution
    # executions = automation.history()
    executions = list(project.automation_history())
    assert len(executions) == 1

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

    # Trigger the automation by creating a new artifact version in the collection
    artifact = Artifact(name=collection.name, type=collection.type)

    placeholder_path = tmp_path / f"{make_name('placeholder')}.txt"
    placeholder_path.write_text(f"placeholder-{uuid4()!s}")

    with wandb.init(entity=collection.entity, project=collection.name) as run:
        artifact.add_file(str(placeholder_path))
        run.log_artifact(artifact)

    artifact.wait()

    # It might take a moment to execute, so we'll retry, within reason
    # for _ in sleeping_retry(LOOPBACK_TIMEOUT):
    #     if len(automation.history()) > 0:
    #         break

    time.sleep(5)

    # Fetch execution history - should show at least one execution
    # executions = list(automation.history())
    executions = list(collection.automation_history())
    assert len(executions) >= 1

    # Verify the execution has expected properties
    execution = executions[0]
    assert execution.automation_id == automation.id
    assert execution.automation_name == automation.name
    assert execution.triggered_at is not None
    assert execution.state == TriggerExecutionState.FINISHED


# ==============================================================================
# Tests for project.automation_history()
# ==============================================================================


def test_project_automation_history_returns_iterable(project: Project):
    """Test that project.automation_history() returns an iterable and is sized."""
    history = project.automation_history()

    len(history)  # Will raise TypeError if not Sized
    list(history)  # Will raise TypeError if not iterable


def test_project_automation_history_empty_when_no_executions(project: Project):
    """Test that project automation history works with real server.

    Since we haven't triggered any automations in this project, the history
    should be empty.
    """
    history = list(project.automation_history())
    assert len(history) == 0


def test_project_automation_history_respects_per_page_parameter(project: Project):
    """Test that per_page parameter is accepted."""
    history = list(project.automation_history(per_page=25))
    # History is empty since no automations have been triggered
    assert history == []


# TODO: FIX THIS TEST
def test_project_automation_history_includes_all_executions(
    user: str,
    project: Project,
    api: wandb.Api,
    make_name: Callable[[str], str],
):
    """Test that project.automation_history() includes executions from all automations in the project."""
    # Create two automations in the project
    automation1 = api.create_automation(
        OnLinkArtifact(scope=project) >> DoNothing(),
        name=make_name("automation-1"),
    )
    automation2 = api.create_automation(
        OnLinkArtifact(scope=project) >> DoNothing(),
        name=make_name("automation-2"),
    )

    try:
        # Verify empty history before triggering
        assert len(list(project.automation_history())) == 0

        # Trigger both automations by linking an artifact
        artifact_name = make_name("test-artifact")
        with wandb.init(entity=user, project=project.name) as run:
            artifact = Artifact(artifact_name, type="dataset")
            logged_artifact = run.log_artifact(artifact)
            logged_artifact.wait()

        # Fetch project history - should show executions from both automations
        project_history = list(project.automation_history())
        assert len(project_history) >= 2

        # Verify we have executions from both automations
        automation_ids = {exec.automation_id for exec in project_history}
        assert automation1.id in automation_ids
        assert automation2.id in automation_ids

    finally:
        # Cleanup
        api.delete_automation(automation1)
        api.delete_automation(automation2)


# ==============================================================================
# Tests for artifact_collection.automation_history()
# ==============================================================================


def test_artifact_collection_automation_history_returns_iterable(
    artifact_collection: ArtifactCollection,
):
    """Test that artifact_collection.automation_history() returns an iterable and is sized."""
    history = artifact_collection.automation_history()

    len(history)  # Will raise TypeError if not Sized
    list(history)  # Will raise TypeError if not iterable


def test_artifact_collection_automation_history_empty_when_no_executions(
    artifact_collection: ArtifactCollection,
):
    """Test that artifact collection automation history works with real server."""
    history = list(artifact_collection.automation_history())
    assert len(history) == 0


def test_artifact_collection_automation_history_respects_per_page_parameter(
    artifact_collection: ArtifactCollection,
):
    """Test that per_page parameter is accepted."""
    history = list(artifact_collection.automation_history(per_page=15))
    # History is empty since no automations have been triggered
    assert history == []


# TODO: FIX THIS TEST
def test_artifact_collection_automation_history_includes_executions(
    user: str,
    project: Project,
    artifact_collection: ArtifactCollection,
    api: wandb.Api,
    make_name: Callable[[str], str],
):
    """Test that artifact_collection.automation_history() records executions."""
    # Create an automation scoped to the collection
    automation = api.create_automation(
        OnCreateArtifact(scope=artifact_collection) >> DoNothing(),
        name=make_name("collection-automation"),
    )

    try:
        # Verify empty history before triggering
        assert len(list(artifact_collection.automation_history())) == 0

        # Trigger the automation by creating a new artifact version
        with wandb.init(entity=user, project=project.name) as run:
            artifact = Artifact(
                artifact_collection.name,
                type=artifact_collection.type,
            )
            logged_artifact = run.log_artifact(artifact)
            logged_artifact.wait()

        # Fetch collection history - should show the execution
        collection_history = list(artifact_collection.automation_history())
        assert len(collection_history) >= 1

        # Verify it's our automation
        executed_automation = collection_history[0]
        assert executed_automation.automation_id == automation.id

    finally:
        # Cleanup
        api.delete_automation(automation)


# ==============================================================================
# Cross-scope consistency tests
# ==============================================================================


def test_all_history_methods_have_consistent_signature(
    automation: Automation,
    project: Project,
    artifact_collection: ArtifactCollection,
):
    """Test that all three history methods accept the same parameters and return sized iterables."""
    # All should accept per_page parameter and return sized iterables
    auto_history = automation.history(per_page=10)
    proj_history = project.automation_history(per_page=10)
    coll_history = artifact_collection.automation_history(per_page=10)

    # Verify all are sized (support len())
    len(auto_history)
    len(proj_history)
    len(coll_history)

    # Verify all are iterable
    list(auto_history)
    list(proj_history)
    list(coll_history)
