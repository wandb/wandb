from __future__ import annotations

from dataclasses import dataclass

from pytest import fixture, raises
from wandb import Artifact
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.artifact_state import ArtifactState
from wandb.sdk.artifacts.storage_handlers.gcs_handler import (
    GCSHandler,
    _GCSIsADirectoryError,
)


@dataclass
class Blob:
    """Mock GCS Blob for testing."""

    name: str
    md5_hash: str | None = "1234567890abcde"
    etag: str = "1234567890abcde"
    generation: int = 1
    size: int = 10


@fixture
def artifact() -> Artifact:
    return Artifact(type="dataset", name="data-artifact")


def mock_gcs(
    artifact,
    blobs: list[str | Blob],
    versioning_enabled: bool = True,
):
    """Mock GCS client with explicit blob declarations.

    Args:
        artifact: The artifact to mock GCS for.
        blobs: List of blob names (str) or Blob objects with full customization.
        versioning_enabled: Whether bucket versioning is enabled.
    """
    # Normalize blobs: convert strings to Blob objects
    normalized_blobs = [Blob(name=b) if isinstance(b, str) else b for b in blobs]

    class GSBucket:
        def __init__(self):
            self.versioning_enabled = versioning_enabled

        def reload(self, *args, **kwargs):
            return

        def get_blob(self, key, *args, **kwargs):
            generation = kwargs.get("generation")
            for blob in normalized_blobs:
                if blob.name == key:
                    if generation is None or blob.generation == generation:
                        return blob
            return None

        def list_blobs(self, *args, **kwargs):
            prefix: str = kwargs.get("prefix", "")
            max_results: int | None = kwargs.get("max_results")
            results = [b for b in normalized_blobs if b.name.startswith(prefix)]
            if max_results is not None:
                results = results[:max_results]
            return results

    class GSClient:
        def bucket(self, bucket):
            return GSBucket()

    mock = GSClient()
    for handler in artifact.manifest.storage_policy._handler._handlers:
        if isinstance(handler, GCSHandler):
            handler._client = mock
    return mock


def test_add_gs_reference_object(artifact):
    mock_gcs(artifact, blobs=["my_object.pb"])
    artifact.add_reference("gs://my-bucket/my_object.pb")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest_contents = artifact.manifest.to_manifest_json()["contents"]
    assert manifest_contents == {
        "my_object.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_object.pb",
            "extra": {"versionID": 1},
            "size": 10,
        },
    }


def test_load_gs_reference_object_without_generation_and_mismatched_etag(
    artifact,
):
    mock_gcs(artifact, blobs=["my_object.pb"])
    artifact.add_reference("gs://my-bucket/my_object.pb")
    artifact._state = ArtifactState.COMMITTED
    entry = artifact.get_entry("my_object.pb")
    entry.extra = {}
    entry.digest = "abad0"

    with raises(ValueError, match="Digest mismatch"):
        entry.download()


def test_add_gs_reference_object_with_version(artifact):
    mock_gcs(
        artifact,
        blobs=[
            Blob("my_object.pb", generation=1),
            Blob("my_object.pb", generation=2),
            Blob("my_object.pb", generation=3),
        ],
    )
    artifact.add_reference("gs://my-bucket/my_object.pb#2")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest_contents = artifact.manifest.to_manifest_json()["contents"]
    assert manifest_contents == {
        "my_object.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_object.pb",
            "extra": {"versionID": 2},
            "size": 10,
        },
    }


def test_add_gs_reference_object_with_name(artifact):
    mock_gcs(artifact, blobs=["my_object.pb"])
    artifact.add_reference("gs://my-bucket/my_object.pb", name="renamed.pb")

    assert artifact.digest == "bd85fe009dc9e408a5ed9b55c95f47b2"
    manifest_contents = artifact.manifest.to_manifest_json()["contents"]
    assert manifest_contents == {
        "renamed.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_object.pb",
            "extra": {"versionID": 1},
            "size": 10,
        },
    }


def test_add_gs_reference_path(capsys, artifact):
    mock_gcs(artifact, blobs=["my_object.pb", "my_other_object.pb"])
    artifact.add_reference("gs://my-bucket/")

    assert artifact.digest == "17955d00a20e1074c3bc96c74b724bfe"
    manifest_contents = artifact.manifest.to_manifest_json()["contents"]
    assert manifest_contents == {
        "my_object.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_object.pb",
            "extra": {"versionID": 1},
            "size": 10,
        },
        "my_other_object.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_other_object.pb",
            "extra": {"versionID": 1},
            "size": 10,
        },
    }
    _, err = capsys.readouterr()
    assert "Added 2 objects" in err


def test_add_gs_reference_object_no_md5(artifact):
    mock_gcs(artifact, blobs=[Blob("my_object.pb", md5_hash=None)])
    artifact.add_reference("gs://my-bucket/my_object.pb")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest_contents = artifact.manifest.to_manifest_json()["contents"]
    assert manifest_contents == {
        "my_object.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_object.pb",
            "extra": {"versionID": 1},
            "size": 10,
        },
    }


def test_add_gs_reference_with_dir_paths(artifact):
    mock_gcs(artifact, blobs=["my_folder/", "my_folder/my_other_object.pb"])
    artifact.add_reference("gs://my-bucket/my_folder/")

    # uploading a reference to a folder path should add entries for
    # everything returned by the list_blobs call
    assert len(artifact.manifest.entries) == 1
    manifest_contents = artifact.manifest.to_manifest_json()["contents"]
    assert manifest_contents == {
        "my_other_object.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_folder/my_other_object.pb",
            "extra": {"versionID": 1},
            "size": 10,
        },
    }


def test_load_gs_reference_with_dir_paths(artifact):
    mock = mock_gcs(artifact, blobs=["my_folder/", "my_folder/my_other_object.pb"])
    artifact.add_reference("gs://my-bucket/my_folder/")

    gcs_handler = GCSHandler()
    gcs_handler._client = mock

    # simple case where ref ends with "/"
    simple_entry = ArtifactManifestEntry(
        path="my-bucket/my_folder",
        ref="gs://my-bucket/my_folder/",
        digest="1234567890abcde",
        size=0,
        extra={"versionID": 1},
    )
    with raises(_GCSIsADirectoryError):
        gcs_handler.load_path(simple_entry, local=True)

    # case where we didn't store "/" and have to use get_blob
    entry = ArtifactManifestEntry(
        path="my-bucket/my_folder",
        ref="gs://my-bucket/my_folder",
        digest="1234567890abcde",
        size=0,
        extra={"versionID": 1},
    )
    with raises(_GCSIsADirectoryError):
        gcs_handler.load_path(entry, local=True)
