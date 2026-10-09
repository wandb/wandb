from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from google.api_core.exceptions import Forbidden, ServiceUnavailable, Unauthorized
from google.auth.exceptions import InvalidOperation
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


# ---------------------------------------------------------------------------
# Tests for the `storage.objects.list`-only fallback, used when the caller's
# credentials lack `storage.objects.get`.
#
# `mock_gcs` above is deliberately minimal and covers the `get_blob` path. The
# fake below is closer to the real service: a flat, sorted namespace, lazy
# listing, noncurrent generations, and a `get_blob` that can be forbidden.
# ---------------------------------------------------------------------------

BUCKET = "my-bucket"


@dataclass
class FakeBlob:
    name: str
    generation: int = 1
    etag: str = ""
    size: int = 10
    live: bool = True

    def __post_init__(self) -> None:
        self.etag = self.etag or f"etag-{self.name}-{self.generation}"


class _FailedListingError(Exception):
    """Raised by the fake when a later page of a listing fails."""


@dataclass
class FakeBucket:
    blobs: list[FakeBlob]
    forbid_get: bool = False
    get_error: Exception | None = None
    fail_after: int | None = None
    # Exception raised when `fail_after` triggers; defaults to _FailedListingError.
    fail_error: Exception | None = None
    # Models list permission granted on a managed folder: listing any prefix
    # outside `list_scope` is forbidden.
    list_scope: str | None = None
    # Raised by the exact-key probe (the `max_results=1` listing) only.
    probe_error: Exception | None = None
    get_calls: list[tuple[str, Any]] = field(default_factory=list)
    list_calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.blobs = sorted(self.blobs, key=lambda b: (b.name, b.generation))

    def get_blob(self, key: str, generation: Any = None, **kwargs: Any):
        self.get_calls.append((key, generation))
        if self.get_error is not None:
            raise self.get_error
        if self.forbid_get:
            raise Forbidden("403 GET objects.get access denied")
        gen = int(generation) if generation is not None else None
        for blob in self.blobs:
            if blob.name != key:
                continue
            if gen is None and blob.live:
                return blob
            if gen is not None and blob.generation == gen:
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
        # A generator, so (like the real client) nothing happens until it is
        # iterated and an error can surface part way through.
        if self.list_scope is not None and not prefix.startswith(self.list_scope):
            raise Forbidden(f"403 LIST denied outside {self.list_scope!r}")
        if self.probe_error is not None and max_results == 1:
            raise self.probe_error
        n = 0
        for blob in self.blobs:
            if not blob.name.startswith(prefix) or not (versions or blob.live):
                continue
            if max_results is not None and n >= max_results:
                return
            if self.fail_after is not None and n >= self.fail_after:
                raise self.fail_error or _FailedListingError(
                    f"listing failed after {n} blobs"
                )
            yield blob
            n += 1


class FakeClient:
    def __init__(self, bucket: FakeBucket) -> None:
        self._bucket = bucket

    def bucket(self, name: str) -> FakeBucket:
        assert name == BUCKET
        return self._bucket


def add_reference(
    bucket: FakeBucket, uri: str, name: str | None = None, **kwargs: Any
) -> dict[str, tuple]:
    """Add a reference against `bucket` and return the resulting entries."""
    artifact = Artifact(type="dataset", name="data-artifact")
    for handler in artifact.manifest.storage_policy._handler._handlers:
        if isinstance(handler, GCSHandler):
            handler._client = FakeClient(bucket)
    artifact.add_reference(uri, name=name, **kwargs)
    return {
        path: (e.ref, e.digest, e.size, (e.extra or {}).get("versionID"))
        for path, e in artifact.manifest.entries.items()
    }


def uri_of(key: str) -> str:
    return f"gs://{BUCKET}/{key}"


# (blobs, reference, name, expected entry paths)
LIST_ONLY_CASES = {
    "single_file": ([FakeBlob("model.ckpt")], "model.ckpt", None, {"model.ckpt"}),
    "file_with_dotted_sibling": (
        [FakeBlob("model.ckpt"), FakeBlob("model.ckpt.bak")],
        "model.ckpt",
        None,
        {"model.ckpt"},
    ),
    "file_with_dash_sibling": (
        [FakeBlob("data"), FakeBlob("data-1.txt")],
        "data",
        None,
        {"data"},
    ),
    "file_and_same_named_folder": (
        [FakeBlob("data"), FakeBlob("data/x")],
        "data",
        None,
        {"data"},
    ),
    "nested_file": (
        [FakeBlob("a/b/model.ckpt"), FakeBlob("a/b/model.ckpt.bak")],
        "a/b/model.ckpt",
        None,
        {"model.ckpt"},
    ),
    "folder_without_slash": (
        [FakeBlob("d/a"), FakeBlob("d/b"), FakeBlob("other")],
        "d",
        None,
        {"a", "b"},
    ),
    "folder_with_slash": (
        [FakeBlob("d/a"), FakeBlob("d/b"), FakeBlob("other")],
        "d/",
        None,
        {"a", "b"},
    ),
    "nested_folder": (
        [FakeBlob("d/a"), FakeBlob("d/sub/b")],
        "d",
        None,
        {"a", "sub/b"},
    ),
    "folder_marker_with_slash": (
        [FakeBlob("d/", size=0), FakeBlob("d/a")],
        "d/",
        None,
        {"a"},
    ),
    "folder_marker_without_slash": (
        [FakeBlob("d/", size=0), FakeBlob("d/a")],
        "d",
        None,
        {"a"},
    ),
    "name_override_file": (
        [FakeBlob("f.bin"), FakeBlob("f.bin.bak")],
        "f.bin",
        "renamed.bin",
        {"renamed.bin"},
    ),
    "name_override_folder": (
        [FakeBlob("d/a"), FakeBlob("d/sub/b")],
        "d",
        "data",
        {"data/a", "data/sub/b"},
    ),
    "name_override_folder_with_slash": (
        [FakeBlob("d/a"), FakeBlob("d/sub/b")],
        "d/",
        "data",
        {"data/a", "data/sub/b"},
    ),
    "versioned_live_generation": (
        [FakeBlob("f", 1, live=False), FakeBlob("f", 2), FakeBlob("f-x", 2)],
        "f#2",
        None,
        {"f"},
    ),
    "versioned_noncurrent_generation": (
        [FakeBlob("f", 1, live=False), FakeBlob("f", 2)],
        "f#1",
        None,
        {"f"},
    ),
    "versioned_leading_zero": (
        [FakeBlob("f", 1), FakeBlob("f", 2)],
        "f#01",
        None,
        {"f"},
    ),
    "versioned_with_name": (
        [FakeBlob("f", 1, live=False), FakeBlob("f", 2)],
        "f#1",
        "renamed",
        {"renamed"},
    ),
}


@pytest.mark.parametrize(
    ("blobs", "ref", "name", "expected_paths"),
    list(LIST_ONLY_CASES.values()),
    ids=list(LIST_ONLY_CASES),
)
def test_list_only_matches_get_path(blobs, ref, name, expected_paths):
    """With only list permission, the entries match those from the get path."""
    via_get = add_reference(FakeBucket(blobs), uri_of(ref), name=name)

    forbidden = FakeBucket(blobs, forbid_get=True)
    via_list = add_reference(forbidden, uri_of(ref), name=name)

    assert set(via_get) == expected_paths
    assert via_list == via_get
    # The only `get_blob` call is the probe that was refused.
    assert len(forbidden.get_calls) == 1


def test_list_only_single_file_entry():
    bucket = FakeBucket([FakeBlob("m.ckpt", 7, size=123)], forbid_get=True)
    assert add_reference(bucket, uri_of("m.ckpt")) == {
        "m.ckpt": (uri_of("m.ckpt"), "etag-m.ckpt-7", 123, 7)
    }


def test_list_only_folder_excludes_siblings_of_the_prefix():
    # Deliberate difference from the `get_blob` path, which lists the bare
    # prefix `d` and also returns `d-1.txt` with the wrong ref `gs://.../d`.
    bucket = FakeBucket(
        [FakeBlob("d/a", 1), FakeBlob("d/b", 2), FakeBlob("d-1.txt", 3)],
        forbid_get=True,
    )
    assert add_reference(bucket, uri_of("d")) == {
        "a": (uri_of("d/a"), "etag-d/a-1", 10, 1),
        "b": (uri_of("d/b"), "etag-d/b-2", 10, 2),
    }
    assert [c["prefix"] for c in bucket.list_calls] == ["d", "d/"]


def test_list_only_file_probe_requests_one_result():
    bucket = FakeBucket([FakeBlob("f"), FakeBlob("f.bak")], forbid_get=True)
    add_reference(bucket, uri_of("f"))
    assert bucket.list_calls == [{"prefix": "f", "max_results": 1, "versions": False}]


def test_list_only_folder_listing_is_bounded_by_max_objects():
    bucket = FakeBucket([FakeBlob("d/a"), FakeBlob("d/b")], forbid_get=True)
    add_reference(bucket, uri_of("d/"), max_objects=5)
    assert bucket.list_calls == [{"prefix": "d/", "max_results": 5, "versions": False}]


def test_list_only_versioned_listing_requests_versions():
    bucket = FakeBucket([FakeBlob("f", 1), FakeBlob("f", 2)], forbid_get=True)
    add_reference(bucket, uri_of("f#2"))
    assert bucket.list_calls == [{"prefix": "f", "max_results": None, "versions": True}]


def test_list_only_versioned_miss_raises():
    bucket = FakeBucket([FakeBlob("f", 1), FakeBlob("f-x", 9)], forbid_get=True)
    with raises(ValueError, match="Object does not exist"):
        add_reference(bucket, uri_of("f#9"))


def test_list_only_version_on_folder_reference_raises():
    bucket = FakeBucket([FakeBlob("d/a")], forbid_get=True)
    with raises(ValueError, match="not valid on a folder reference"):
        add_reference(bucket, uri_of("d/#1"))


def test_list_only_non_integer_version_raises():
    # The real client rejects a non-integer generation inside `get_blob`
    # before any request, so this guards the helper itself rather than a
    # path a real 403 can reach.
    bucket = FakeBucket([FakeBlob("f", 1)], forbid_get=True)
    with raises(ValueError, match="must be an integer"):
        add_reference(bucket, uri_of("f#abc"))


def test_list_only_partial_filename_prefix_raises():
    bucket = FakeBucket([FakeBlob("train-0"), FakeBlob("train-1")], forbid_get=True)
    with raises(ValueError, match="neither an object nor a folder prefix"):
        add_reference(bucket, uri_of("train-"))


def test_list_only_nonexistent_key_is_empty():
    bucket = FakeBucket([FakeBlob("other")], forbid_get=True)
    assert add_reference(bucket, uri_of("nope")) == {}


@pytest.mark.parametrize("ref", ["d", "d/"])
def test_list_only_marker_only_folder_is_empty(ref):
    bucket = FakeBucket([FakeBlob("d/", size=0)], forbid_get=True)
    assert add_reference(bucket, uri_of(ref)) == {}


@pytest.mark.parametrize("ref", ["d", "d/"])
def test_list_only_folder_listing_error_propagates(ref):
    bucket = FakeBucket(
        [FakeBlob("d/a"), FakeBlob("d/b"), FakeBlob("d/c")],
        forbid_get=True,
        fail_after=1,
    )
    with raises(_FailedListingError):
        add_reference(bucket, uri_of(ref))


@pytest.mark.parametrize(
    "error",
    [
        Unauthorized("401 bad credentials"),
        ServiceUnavailable("503 try later"),
        # What an anonymous client raises when a 401 triggers a token refresh.
        InvalidOperation("Anonymous credentials cannot be refreshed."),
    ],
    ids=["unauthorized", "service_unavailable", "anonymous_refresh"],
)
def test_other_get_errors_propagate_without_listing(error):
    bucket = FakeBucket([FakeBlob("f")], get_error=error)
    with raises(type(error)):
        add_reference(bucket, uri_of("f"))
    assert len(bucket.get_calls) == 1
    assert bucket.list_calls == []


def test_get_permission_never_lists_for_single_file():
    bucket = FakeBucket([FakeBlob("f"), FakeBlob("f.bak")])
    assert set(add_reference(bucket, uri_of("f"))) == {"f"}
    assert len(bucket.get_calls) == 1
    assert bucket.list_calls == []


def test_get_permission_versioned_file_never_lists():
    bucket = FakeBucket([FakeBlob("f", 1, live=False), FakeBlob("f", 2)])
    assert set(add_reference(bucket, uri_of("f#1"))) == {"f"}
    assert len(bucket.get_calls) == 1
    assert bucket.list_calls == []


# ---------------------------------------------------------------------------
# List permission scoped to a managed folder. The bare prefix `managed` is
# outside the folder `managed/`, so the exact-key probe is denied even though
# the folder listing is allowed.
# ---------------------------------------------------------------------------


def scoped_bucket(blobs: list[FakeBlob], **kwargs: Any) -> FakeBucket:
    return FakeBucket(blobs, forbid_get=True, list_scope="managed/", **kwargs)


def test_scoped_list_folder_without_trailing_slash():
    bucket = scoped_bucket([FakeBlob("managed/a"), FakeBlob("managed/sub/b")])
    assert set(add_reference(bucket, uri_of("managed"))) == {"a", "sub/b"}
    assert [c["prefix"] for c in bucket.list_calls] == ["managed", "managed/"]


def test_scoped_list_folder_with_trailing_slash():
    bucket = scoped_bucket([FakeBlob("managed/a")])
    assert set(add_reference(bucket, uri_of("managed/"))) == {"a"}
    assert [c["prefix"] for c in bucket.list_calls] == ["managed/"]


@pytest.mark.parametrize(
    "blobs",
    [[], [FakeBlob("managed/", size=0)]],
    ids=["empty", "marker_only"],
)
def test_scoped_list_denied_probe_then_empty_folder_is_empty(blobs):
    bucket = scoped_bucket(blobs)
    assert add_reference(bucket, uri_of("managed")) == {}


def test_scoped_list_outside_scope_propagates_forbidden():
    bucket = scoped_bucket([FakeBlob("managed/a")])
    with raises(Forbidden):
        add_reference(bucket, uri_of("other"))
    assert [c["prefix"] for c in bucket.list_calls] == ["other", "other/"]


def test_scoped_list_exact_file_with_sibling():
    bucket = scoped_bucket(
        [FakeBlob("managed/model.ckpt"), FakeBlob("managed/model.ckpt.bak")]
    )
    assert set(add_reference(bucket, uri_of("managed/model.ckpt"))) == {"model.ckpt"}


@pytest.mark.parametrize("fragment", ["2", "02"])
def test_scoped_list_versioned_file(fragment):
    bucket = scoped_bucket(
        [FakeBlob("managed/f", 1, live=False), FakeBlob("managed/f", 2)]
    )
    entries = add_reference(bucket, uri_of(f"managed/f#{fragment}"))
    assert entries["f"][3] == 2


def test_scoped_list_inaccessible_same_named_file_yields_folder():
    # Object `managed` is outside the `managed/` scope, so the probe is denied
    # and the accessible folder is returned. A caller with get permission on
    # that object gets the file instead; this is the accepted semantics of a
    # denied probe.
    bucket = scoped_bucket([FakeBlob("managed"), FakeBlob("managed/a")])
    assert set(add_reference(bucket, uri_of("managed"))) == {"a"}


def test_scoped_list_version_on_bare_folder_prefix_propagates_forbidden():
    bucket = scoped_bucket([FakeBlob("managed/a")])
    with raises(Forbidden):
        add_reference(bucket, uri_of("managed#1"))
    # The versioned scan was attempted (and denied); it is not reinterpreted
    # as a folder reference.
    assert bucket.list_calls == [
        {"prefix": "managed", "max_results": None, "versions": True}
    ]


@pytest.mark.parametrize(
    "error",
    [None, Forbidden("403 denied on a later page")],
    ids=["generic_error", "forbidden"],
)
def test_scoped_list_denied_probe_then_folder_error_propagates(error):
    # A Forbidden raised part way through the folder listing must not be
    # mistaken for the probe's Forbidden and swallowed.
    bucket = scoped_bucket(
        [FakeBlob("managed/a"), FakeBlob("managed/b")],
        fail_after=1,
        fail_error=error,
    )
    with raises(type(error) if error else _FailedListingError) as excinfo:
        add_reference(bucket, uri_of("managed"))
    if error is not None:
        # The listing's own error surfaces, not the probe's or get_blob's 403.
        assert excinfo.value is error


@pytest.mark.parametrize(
    "error",
    [Unauthorized("401 bad credentials"), ServiceUnavailable("503 try later")],
    ids=["unauthorized", "service_unavailable"],
)
def test_probe_non_forbidden_error_propagates_without_folder_retry(error):
    bucket = FakeBucket([FakeBlob("d/a")], forbid_get=True, probe_error=error)
    with raises(type(error)):
        add_reference(bucket, uri_of("d"))
    assert [c["prefix"] for c in bucket.list_calls] == ["d"]
