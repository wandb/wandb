from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from google.api_core.exceptions import Forbidden, ServiceUnavailable
from pytest import fixture, raises
from wandb import Artifact
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.artifact_state import ArtifactState
from wandb.sdk.artifacts.storage_handlers.gcs_handler import (
    GCSHandler,
    _GCSIsADirectoryError,
)


def mock_gcs(artifact, override_blob_name="my_object.pb", path=False, hash=True):
    class Blob:
        def __init__(self, name=override_blob_name, metadata=None, generation=None):
            self.md5_hash = "1234567890abcde" if hash else None
            self.etag = "1234567890abcde"
            self.generation = generation or "1"
            self.name = name
            self.size = 10

    class GSBucket:
        def __init__(self):
            self.versioning_enabled = True

        def reload(self, *args, **kwargs):
            return

        def get_blob(self, key=override_blob_name, *args, **kwargs):
            return (
                None
                if path or key != override_blob_name
                else Blob(generation=kwargs.get("generation"))
            )

        def list_blobs(self, *args, **kwargs):
            if override_blob_name.endswith("/"):
                return [
                    Blob(name=override_blob_name),
                    Blob(name=os.path.join(override_blob_name, "my_other_object.pb")),
                ]
            else:
                return [
                    Blob(name=override_blob_name),
                    Blob(name="my_other_object.pb"),
                ]

    class GSClient:
        def bucket(self, bucket):
            return GSBucket()

    mock = GSClient()
    for handler in artifact.manifest.storage_policy._handler._handlers:
        if isinstance(handler, GCSHandler):
            handler._client = mock
    return mock


@fixture
def artifact() -> Artifact:
    return Artifact(type="dataset", name="data-artifact")


def test_add_gs_reference_object(artifact):
    mock_gcs(artifact)
    artifact.add_reference("gs://my-bucket/my_object.pb")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest_contents = artifact.manifest.to_manifest_json()["contents"]
    assert manifest_contents == {
        "my_object.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_object.pb",
            "extra": {"versionID": "1"},
            "size": 10,
        },
    }


def test_load_gs_reference_object_without_generation_and_mismatched_etag(
    artifact,
):
    mock_gcs(artifact)
    artifact.add_reference("gs://my-bucket/my_object.pb")
    artifact._state = ArtifactState.COMMITTED
    entry = artifact.get_entry("my_object.pb")
    entry.extra = {}
    entry.digest = "abad0"

    with raises(ValueError, match="Digest mismatch"):
        entry.download()


def test_add_gs_reference_object_with_version(artifact):
    mock_gcs(artifact)
    artifact.add_reference("gs://my-bucket/my_object.pb#2")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest_contents = artifact.manifest.to_manifest_json()["contents"]
    assert manifest_contents == {
        "my_object.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_object.pb",
            "extra": {"versionID": "2"},
            "size": 10,
        },
    }


def test_add_gs_reference_object_with_name(artifact):
    mock_gcs(artifact)
    artifact.add_reference("gs://my-bucket/my_object.pb", name="renamed.pb")

    assert artifact.digest == "bd85fe009dc9e408a5ed9b55c95f47b2"
    manifest_contents = artifact.manifest.to_manifest_json()["contents"]
    assert manifest_contents == {
        "renamed.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_object.pb",
            "extra": {"versionID": "1"},
            "size": 10,
        },
    }


def test_add_gs_reference_path(capsys, artifact):
    mock_gcs(artifact, path=True)
    artifact.add_reference("gs://my-bucket/")

    assert artifact.digest == "17955d00a20e1074c3bc96c74b724bfe"
    manifest_contents = artifact.manifest.to_manifest_json()["contents"]
    assert manifest_contents == {
        "my_object.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_object.pb",
            "extra": {"versionID": "1"},
            "size": 10,
        },
        "my_other_object.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_other_object.pb",
            "extra": {"versionID": "1"},
            "size": 10,
        },
    }
    _, err = capsys.readouterr()
    assert "Generating checksum" in err


def test_add_gs_reference_object_no_md5(artifact):
    mock_gcs(artifact, hash=False)
    artifact.add_reference("gs://my-bucket/my_object.pb")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest_contents = artifact.manifest.to_manifest_json()["contents"]
    assert manifest_contents == {
        "my_object.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_object.pb",
            "extra": {"versionID": "1"},
            "size": 10,
        },
    }


def test_add_gs_reference_with_dir_paths(artifact):
    mock_gcs(artifact, override_blob_name="my_folder/")
    artifact.add_reference("gs://my-bucket/my_folder/")

    # uploading a reference to a folder path should add entries for
    # everything returned by the list_blobs call
    assert len(artifact.manifest.entries) == 1
    manifest_contents = artifact.manifest.to_manifest_json()["contents"]
    assert manifest_contents == {
        "my_other_object.pb": {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_folder/my_other_object.pb",
            "extra": {"versionID": "1"},
            "size": 10,
        },
    }


def test_load_gs_reference_with_dir_paths(artifact):
    mock = mock_gcs(artifact, override_blob_name="my_folder/")
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


BUCKET = "my-bucket"


@dataclass
class FakeBlob:
    name: str
    generation: int = 1
    size: int = 10
    live: bool = True

    @property
    def etag(self) -> str:
        return f"etag-{self.name}-{self.generation}"


@dataclass
class FakeBucket:
    blobs: list[FakeBlob]
    get_error: Exception | None = None
    list_error: Exception | None = None  # raised when the listing is iterated
    list_calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.blobs = sorted(self.blobs, key=lambda b: (b.name, b.generation))

    def get_blob(self, key: str, generation: Any = None, **kwargs: Any):
        if self.get_error is not None:
            raise self.get_error
        gen = int(generation) if generation is not None else None
        for blob in self.blobs:
            if blob.name == key and (
                blob.live if gen is None else blob.generation == gen
            ):
                return blob
        return None

    def list_blobs(
        self,
        prefix: str = "",
        max_results: int | None = None,
        versions: bool = False,
        **kwargs: Any,
    ) -> Iterator[FakeBlob]:
        self.list_calls.append(
            {"prefix": prefix, "max_results": max_results, "versions": versions}
        )
        return self._iter_blobs(prefix, max_results, versions)

    def _iter_blobs(
        self, prefix: str, max_results: int | None, versions: bool
    ) -> Iterator[FakeBlob]:
        if self.list_error is not None:
            raise self.list_error
        n = 0
        for blob in self.blobs:
            if not blob.name.startswith(prefix) or not (versions or blob.live):
                continue
            if max_results is not None and n >= max_results:
                return
            yield blob
            n += 1


def list_only(blobs: list[FakeBlob], **kwargs: Any) -> FakeBucket:
    return FakeBucket(blobs, get_error=Forbidden("403 objects.get denied"), **kwargs)


def add_reference(
    bucket: FakeBucket, key: str, name: str | None = None
) -> dict[str, tuple]:
    """Add `gs://{BUCKET}/{key}` against `bucket`; return its entries by path."""
    artifact = Artifact(type="dataset", name="data-artifact")
    for handler in artifact.manifest.storage_policy._handler._handlers:
        if isinstance(handler, GCSHandler):
            handler._client = type("Client", (), {"bucket": lambda _, name: bucket})()
    artifact.add_reference(f"gs://{BUCKET}/{key}", name=name)
    return {
        path: (e.ref, e.digest, e.size, (e.extra or {}).get("versionID"))
        for path, e in artifact.manifest.entries.items()
    }


@pytest.mark.parametrize(
    ("blobs", "key", "name", "expected_paths"),
    [
        pytest.param(
            [
                FakeBlob("m", 1, live=False),
                FakeBlob("m", 2),
                FakeBlob("m.bak"),
                FakeBlob("m/x"),
            ],
            "m",
            None,
            {"m"},
            id="file",
        ),
        pytest.param(
            [FakeBlob("d/a"), FakeBlob("d/sub/b"), FakeBlob("other")],
            "d",
            None,
            {"a", "sub/b"},
            id="folder",
        ),
        pytest.param(
            [FakeBlob("d/a"), FakeBlob("d/sub/b")],
            "d/",
            "data",
            {"data/a", "data/sub/b"},
            id="folder_with_slash_and_name",
        ),
        pytest.param(
            [FakeBlob("d/", size=0), FakeBlob("d/a")],
            "d",
            None,
            {"a"},
            id="marker_folder",
        ),
        pytest.param(
            [
                FakeBlob("f", 1, live=False),
                FakeBlob("f", 2, live=False),
                FakeBlob("f", 3),
            ],
            "f#2",
            None,
            {"f"},
            id="noncurrent_generation",
        ),
        pytest.param([FakeBlob("other")], "nope", None, set(), id="missing_key"),
    ],
)
def test_list_only_matches_get(blobs, key, name, expected_paths):
    via_get = add_reference(FakeBucket(blobs), key, name)
    via_list = add_reference(list_only(blobs), key, name)

    assert set(via_get) == expected_paths
    assert via_list == via_get


def test_list_only_versioned_miss_raises():
    bucket = list_only([FakeBlob("f", 1), FakeBlob("f-x", 9)])
    with raises(ValueError, match="Object does not exist"):
        add_reference(bucket, "f#9")


def test_list_only_probe_requests_one_result():
    bucket = list_only([FakeBlob("f"), FakeBlob("f.bak")])
    add_reference(bucket, "f")
    assert bucket.list_calls == [{"prefix": "f", "max_results": 1, "versions": False}]


def test_other_get_errors_propagate_without_listing():
    bucket = FakeBucket([FakeBlob("f")], get_error=ServiceUnavailable("503"))
    with raises(ServiceUnavailable):
        add_reference(bucket, "f")
    assert bucket.list_calls == []


def test_list_only_without_list_access_raises_the_list_error():
    error = Forbidden("403 objects.list denied")
    bucket = list_only([FakeBlob("f")], list_error=error)
    with raises(Forbidden) as excinfo:
        add_reference(bucket, "f")
    assert excinfo.value is error


def test_get_access_never_lists_a_file():
    bucket = FakeBucket([FakeBlob("f")], list_error=Forbidden("403"))
    assert set(add_reference(bucket, "f")) == {"f"}
