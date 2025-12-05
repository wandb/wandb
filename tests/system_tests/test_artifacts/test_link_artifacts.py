from __future__ import annotations

import wandb
from pytest import raises


def test_get_artifact_collection_from_linked_artifact(linked_artifact):
    collection = linked_artifact.collection
    assert linked_artifact.entity == collection.entity
    assert linked_artifact.project == collection.project
    assert linked_artifact.name.startswith(collection.name)
    assert linked_artifact.type == collection.type

    collection = linked_artifact.source_collection
    assert linked_artifact.source_entity == collection.entity
    assert linked_artifact.source_project == collection.project
    assert linked_artifact.source_name.startswith(collection.name)
    assert linked_artifact.type == collection.type


def test_unlink_artifact(logged_artifact, linked_artifact, api):
    """Unlinking an artifact in a portfolio collection removes the linked artifact *without* deleting the original."""
    source_artifact = logged_artifact  # For readability

    # Pull these out now in case of state changes
    source_artifact_path = source_artifact.qualified_name
    linked_artifact_path = linked_artifact.qualified_name

    # Consistency/sanity checks in case of changes to upstream fixtures
    assert source_artifact.qualified_name != linked_artifact.qualified_name
    assert api.artifact_exists(source_artifact_path) is True
    assert api.artifact_exists(linked_artifact_path) is True

    linked_artifact.unlink()

    # Now the source artifact should still exist, the link should not
    assert api.artifact_exists(source_artifact_path) is True
    assert api.artifact_exists(linked_artifact_path) is False

    # Unlinking the source artifact should not be possible
    with raises(ValueError, match=r"use 'Artifact.delete' instead"):
        source_artifact.unlink()

    # ... and the source artifact should *still* exist
    assert api.artifact_exists(source_artifact_path) is True


def test_link_artifact_from_run_logs_draft_artifacts_first(user):
    with wandb.init() as run:
        artifact = wandb.Artifact("test-artifact", "test-type")

        assert artifact.is_draft() is True

        linked_artifact = run.link_artifact(artifact, "test-collection")

        # Check that neither the artifact nor the linked artifact are drafts
        assert artifact.is_draft() is False
        assert linked_artifact.is_draft() is False
        assert linked_artifact.source_artifact.is_draft() is False

        assert linked_artifact.id == artifact.id
        assert linked_artifact.is_link is True
        assert linked_artifact.qualified_name != artifact.qualified_name
        assert linked_artifact.source_qualified_name == artifact.qualified_name


def test_link_artifact_without_run_logs_draft_artifacts_first(user):
    artifact = wandb.Artifact("test-artifact", "test-type")

    assert artifact.is_draft() is True

    linked_artifact = artifact.link("test-collection")

    # Check that neither the artifact nor the linked artifact are drafts
    assert artifact.is_draft() is False
    assert linked_artifact.is_draft() is False
    assert linked_artifact.source_artifact.is_draft() is False

    assert linked_artifact.id == artifact.id
    assert linked_artifact.is_link is True
    assert linked_artifact.qualified_name != artifact.qualified_name
    assert linked_artifact.source_qualified_name == artifact.qualified_name


def test_link_artifact_from_run_infers_target_path_from_run(user):
    collection = "test-collection"
    other_proj = "other-project"

    with wandb.init() as run:
        artifact = wandb.Artifact("test-artifact", "test-type")

        # No explicit entity or project in target path
        link_a = run.link_artifact(artifact, collection)
        assert link_a.entity == run.entity
        assert link_a.project == run.project

        # Explicit project, but no entity in target path
        link_b = run.link_artifact(artifact, f"{other_proj}/{collection}")
        assert link_b.entity == run.entity
        assert link_b.project == other_proj


def test_artifact_is_link(user, api):
    with wandb.init() as run:
        artifact_type = "model"
        collection_name = "sequence_name"

        # test is_link upon logging/linking
        artifact = wandb.Artifact(collection_name, artifact_type)
        run.log_artifact(artifact)
        artifact.wait()
        assert artifact.is_link is False

        link_collection = "test_link_collection"
        run.link_artifact(artifact=artifact, target_path=link_collection)

        link_name = f"{artifact.entity}/{artifact.project}/{link_collection}:latest"
        artifact = run.use_artifact(artifact.qualified_name)
        assert artifact.is_link is False

        linked_model_art = run.use_artifact(link_name)
        assert linked_model_art.is_link is True

        # test api
        api_artifact = api.artifact(artifact.qualified_name)
        assert api_artifact.is_link is False

        api_artifact = api.artifact(link_name)
        assert api_artifact.is_link is True

        # test collection api
        source_col = api.artifact_collection(
            artifact_type,
            f"{artifact.entity}/{artifact.project}/{artifact.collection.name}",
        )
        versions = source_col.artifacts()
        assert len(versions) == 1
        assert versions[0].is_link is False

        link_col = api.artifact_collection(
            artifact_type, f"{artifact.entity}/{artifact.project}/{link_collection}"
        )
        versions = link_col.artifacts()
        assert len(versions) == 1
        assert versions[0].is_link is True


def test_linked_artifacts_field(user, api):
    with wandb.init() as run:
        artifact_type = "model"
        collection_name = "sequence_name"

        artifact = wandb.Artifact(collection_name, artifact_type)
        run.log_artifact(artifact)
        artifact.wait()
        assert artifact.is_link is False

        link_collections = [
            "test_link_collection_1",
            "test_link_collection_2",
            "test_link_collection_3",
        ]
        for link_collection in link_collections:
            run.link_artifact(artifact=artifact, target_path=link_collection)

        linked_artifacts = artifact.linked_artifacts
        assert len(linked_artifacts) == len(link_collections)
        for linked in linked_artifacts:
            assert linked.is_link is True
            assert linked.linked_artifacts == []
            assert linked.source_artifact.qualified_name == artifact.qualified_name
            assert linked.collection.name in link_collections

        # test unlink
        linked_artifacts[0].unlink()
        linked_artifacts = artifact.linked_artifacts
        assert len(linked_artifacts) == len(link_collections) - 1
