from __future__ import annotations

import queue
import unittest.mock as mock
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from string import ascii_letters, digits
from unittest.mock import Mock

import requests
import responses
from hypothesis import given
from hypothesis.strategies import from_regex, text
from pytest import fail, mark, raises
from wandb.sdk.artifacts._generated.enums import ArtifactDigestAlgorithm
from wandb.sdk.artifacts._validators import NAME_MAXLEN
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache
from wandb.sdk.artifacts.artifact_instance_cache import artifact_instance_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.artifact_state import ArtifactState
from wandb.sdk.artifacts.exceptions import ArtifactNotLoggedError
from wandb.sdk.artifacts.storage_policies._factories import make_http_session
from wandb.sdk.artifacts.storage_policies._multipart import (
    multipart_download,
    should_multipart_download,
)
from wandb.sdk.lib.hashutil import _md5, _xxh128, md5_string, xxh128_string


def is_cache_hit(cache: ArtifactFileCache, digest: str, size: int) -> bool:
    _, hit, _ = cache.check_digest_obj_path(digest, size)
    return hit


def singleton_queue(x):
    q = queue.Queue()
    q.put(x)
    return q


def test_capped_cache():
    for i in range(101):
        art = Artifact(f"foo-{i}", type="test")
        art._id = f"foo-{i}"
        art._state = "COMMITTED"
        artifact_instance_cache[art.id] = art
    assert len(artifact_instance_cache) == 100


@mark.parametrize("invalid_type", ["job", "wandb-history", "wandb-foo"])
def test_invalid_artifact_type(invalid_type):
    with raises(ValueError, match="reserved for internal use"):
        Artifact("foo", type=invalid_type)


@given(
    invalid_name=(
        text(  # Too many characters
            alphabet={*ascii_letters, *digits, "_", "-", " "},
            min_size=NAME_MAXLEN + 1,
        )
        | from_regex(  # Contains invalid characters
            r"(\w|\d|\s)*(/)(\w|\d|\s)*",
            fullmatch=True,
        )
    )
)
def test_invalid_artifact_name(invalid_name):
    """Prevent users from instantiating an artifact with an invalid name."""
    with raises(ValueError):
        _ = Artifact(invalid_name, type="any")


@mark.parametrize(
    "property",
    [
        "entity",
        "project",
        "version",
        "source_entity",
        "source_project",
        "source_version",
        "ttl",
        "aliases",  # Perhaps shouldn't be restricted? It is today.
        "commit_hash",
        "file_count",  # Probably doesn't need to be restricted, but is today.
        "created_at",
        "updated_at",
        "linked_at",
    ],
)
def test_unlogged_artifact_property_errors(property):
    art = Artifact("foo", type="any")
    error_message = f"'Artifact.{property}' used prior to logging artifact"
    with raises(ArtifactNotLoggedError, match=error_message):
        getattr(art, property)


@mark.parametrize(
    "method",
    [
        "new_draft",
        "download",
        "checkout",
        "verify",
        "file",
        "files",
        "delete",
        "used_by",
        "logged_by",
        "json_encode",
    ],
)
def test_unlogged_artifact_basic_method_errors(method):
    art = Artifact("foo", type="any")
    error_message = f"'Artifact.{method}' used prior to logging artifact"
    with raises(ArtifactNotLoggedError, match=error_message):
        getattr(art, method)()


def test_unlogged_artifact_other_method_errors():
    art = Artifact("foo", type="any")
    with raises(ArtifactNotLoggedError, match="Artifact.get_entry"):
        art.get_entry("pathname")

    with raises(ArtifactNotLoggedError, match="Artifact.get"):
        art["obj_name"]


def test_artifact_manifest_length():
    artifact = Artifact("test-artifact", "test-type")
    assert len(artifact.manifest) == 0
    with artifact.new_file("test.txt") as f:
        f.write("test")
    assert len(artifact.manifest) == 1

    testpath = Path("test.txt")
    testpath.write_text("also a test")
    artifact.add_reference(testpath.resolve().as_uri(), "test2.txt")
    assert len(artifact.manifest) == 2


def test_new_file_accepts_nested_relative_path():
    artifact = Artifact("test-artifact", "test-type")

    with artifact.new_file("nested/test.txt", "w") as f:
        f.write("test")

    assert list(artifact.manifest.entries) == ["nested/test.txt"]
    assert artifact.manifest.entries["nested/test.txt"].size == 4


@mark.parametrize("invalid_name", ["../test.txt", "/test.txt", r"C:\test.txt"])
def test_add_file_rejects_invalid_artifact_path(tmp_path, invalid_name):
    artifact = Artifact("test-artifact", "test-type")
    local_file = tmp_path / "test.txt"
    local_file.write_text("hello")

    with raises(ValueError, match="Invalid artifact path"):
        artifact.add_file(str(local_file), name=invalid_name)


@mark.parametrize("invalid_name", ["../test.txt", "/test.txt", r"C:\test.txt"])
def test_new_file_rejects_invalid_artifact_path(invalid_name):
    artifact = Artifact("test-artifact", "test-type")

    with raises(ValueError, match="Invalid artifact path"):
        with artifact.new_file(invalid_name, "w") as f:
            f.write("test")


def test_manifest_add_entry_rejects_invalid_artifact_path():
    artifact = Artifact("test-artifact", "test-type")
    entry = ArtifactManifestEntry(path="../test.txt", digest="digest")

    with raises(ValueError, match="Invalid artifact path"):
        artifact.manifest.add_entry(entry)


def test_download_with_pathlib_root(monkeypatch):
    artifact = Artifact("test-artifact", "test-type")
    artifact._state = ArtifactState.COMMITTED
    monkeypatch.setattr(artifact, "_download", lambda *args, **kwargs: "")
    monkeypatch.setattr(artifact, "_download_using_core", lambda *args, **kwargs: "")
    custom_path = Path("some/relative/path")
    artifact.download(custom_path)
    assert len(artifact._download_roots) == 1
    root = list(artifact._download_roots)[0]
    path_parts = custom_path.parts
    assert Path(root).parts[-len(path_parts) :] == path_parts


def test_verify_rejects_invalid_artifact_path(tmp_path):
    artifact = Artifact("test-artifact", "test-type")
    artifact._state = ArtifactState.COMMITTED
    bad_entry = ArtifactManifestEntry(path="../test.txt", digest="digest")
    artifact.manifest.entries[bad_entry.path] = bad_entry

    with raises(ValueError, match="Invalid artifact path"):
        artifact.verify(root=str(tmp_path))


def test_artifact_multipart_download_threshold():
    mb = 1024 * 1024
    assert should_multipart_download(100 * mb) is False
    assert should_multipart_download(100 * mb, override=True) is True
    assert should_multipart_download(100 * mb, override=False) is False

    assert should_multipart_download(2080 * mb) is True
    assert should_multipart_download(2080 * mb, override=True) is True
    assert should_multipart_download(2080 * mb, override=False) is False

    assert should_multipart_download(5070 * mb) is True
    assert should_multipart_download(5070 * mb, override=True) is True
    assert should_multipart_download(5070 * mb, override=False) is False


@responses.activate()
def test_artifact_multipart_download_network_error():
    responses.get(
        "https://invalid.com",
        body=requests.exceptions.ConnectionError("Connection refused"),
    )

    opener = mock.mock_open()
    with raises(requests.exceptions.ConnectionError):
        with ThreadPoolExecutor(max_workers=2) as executor:
            multipart_download(
                executor,
                requests.Session(),
                4 * 1024 * 1024 * 1024,
                opener,
                initial_url="https://invalid.com",
                fetch_fn=lambda: "https://invalid.com",
            )
    opener.return_value.seek.assert_not_called()


@responses.activate()
def test_artifact_multipart_download_disk_error():
    resp = responses.get(
        "http://s3.com/file",
        body=b"test",
        status=200,
    )

    opener = mock.mock_open()
    opener.return_value.write.side_effect = OSError("I/O operation on closed file")
    with raises(OSError):
        with ThreadPoolExecutor(max_workers=2) as executor:
            multipart_download(
                executor,
                requests.Session(),
                500 * 1024 * 1024,  # 500MB should have 5 parts
                opener,
                initial_url="https://s3.com/file",
                fetch_fn=lambda: "https://s3.com/file",
            )
    # After first get call has errors, remaining get calls should return without making the call.
    # It can be 5 depending on underlying environment, e.g. it fails on windows from time to time.
    assert resp.call_count <= 5


@responses.activate()
def test_artifact_multipart_download_refresh_presigned_url():
    # S3 returns 403 when presigned url expires. Built-in retry (via make_http_session)
    # handles transient errors like 408/500 by retrying the same url, but can't help with
    # expired urls. The refresh layer handles 403 and fetches a new presigned url.
    #
    # Test flow:
    #   Request t1 (expired)
    #       │
    #       v
    #      403 ──> fetch_fn() gets new URL t2
    #                   │
    #                   v
    #             Request t2
    #                   │
    #                   v
    #                  500 ──> built-in retry
    #                              │
    #                              v
    #                        Request t2
    #                              │
    #                              v
    #                             200 ✓
    rsp1 = responses.get(
        "https://s3.com/file/t1",
        body=b"should be some 403 related error message",
        status=403,
    )
    rsp2 = responses.get(
        "https://s3.com/file/t2",
        body=b"500 retry the same url without refresh",
        status=500,
    )
    rsp3 = responses.get(
        "https://s3.com/file/t2",
        body=b"test",
        status=200,
    )

    fetch_fn = Mock(return_value="https://s3.com/file/t2")

    opener = mock.mock_open()

    with ThreadPoolExecutor(max_workers=2) as executor:
        multipart_download(
            executor,
            make_http_session(),
            100,
            opener,
            initial_url="https://s3.com/file/t1",
            fetch_fn=fetch_fn,
            part_size=100,
        )

    assert fetch_fn.call_count == 1  # fetched new url once
    assert rsp1.call_count == 1
    assert rsp2.call_count == 1
    assert rsp3.call_count == 1


@responses.activate()
def test_artifact_multipart_download_max_refresh_attempts_exceeded():
    resp = responses.get(
        "https://s3.com/file",
        body=b"test",
        status=403,
    )

    opener = mock.mock_open()

    with raises(requests.HTTPError):
        with ThreadPoolExecutor(max_workers=2) as executor:
            multipart_download(
                executor,
                make_http_session(),
                100,
                opener,
                initial_url="https://s3.com/file",
                fetch_fn=lambda: "https://s3.com/file",
                part_size=100,
            )

    assert resp.call_count == 4  # 1 initial + 3 retries


@responses.activate()
def test_artifact_multipart_download_writer_not_on_shared_executor():
    # Test to catch one source of deadlock in multipart download.
    #
    # If the writer and chunk downloader are submitted to the same executor,
    # we can get into a situation where the writer will block on q.get() and the
    # chunk downloader will never execute, causing a deadlock.
    #
    # We test this by passing an executor with 1 worker to `multipart_download`,
    # which will reliably cause the deadlock if the executor is shared.

    responses.get("https://s3.com/file", body=b"x" * 100, status=200)
    opener = mock.mock_open()

    def run_download():
        with ThreadPoolExecutor(max_workers=1) as executor:
            multipart_download(
                executor,
                requests.Session(),
                100,
                opener,
                initial_url="https://s3.com/file",
                fetch_fn=lambda: "https://s3.com/file",
                part_size=100,
            )

    future = ThreadPoolExecutor(max_workers=1).submit(run_download)
    try:
        # Add a timeout to the future to avoid hanging the test.
        future.result(timeout=5)
    except TimeoutError:
        fail("multipart_download deadlocked: writer likely sharing the chunk executor")


def test_offline_artifact_uses_xxh128():
    f = Path("file.txt")
    f.write_text("hello")
    artifact = Artifact("test", type="dataset", digest_algorithm="XXH128")

    artifact.add_file(str(f))
    entry = artifact.manifest.entries["file.txt"]
    assert artifact.digest_algorithm is ArtifactDigestAlgorithm.MANIFEST_XXH128
    assert entry.digest == xxh128_string("hello")


def test_digest_algorithm_with_reference_entries():
    artifact = Artifact("test-artifact", "test-type", digest_algorithm="XXH128")

    f = Path("file.txt")
    f.write_text("hello")
    artifact.add_file(str(f))

    f2 = Path("file2.txt")
    f2.write_text("also a test")
    artifact.add_reference(f2.resolve().as_uri(), "file2.txt")

    assert artifact.digest_algorithm is ArtifactDigestAlgorithm.MANIFEST_XXH128

    # regular file is hashed with XXH128
    entry = artifact.manifest.entries["file.txt"]
    assert entry.digest == xxh128_string("hello")

    # local file reference is hashed with MD5
    ref_entry = artifact.manifest.entries["file2.txt"]
    assert ref_entry.digest == md5_string("also a test")


def test_manifest_digest_uses_xxh128_for_xxh128_artifact():
    f = Path("file.txt")
    f.write_text("hello")
    artifact = Artifact("test", type="dataset", digest_algorithm="XXH128")
    artifact.add_file(str(f))

    file_digest = xxh128_string("hello")
    xxh128_hasher = _xxh128(b"wandb-artifact-manifest-v1\n")
    xxh128_hasher.update(f"file.txt:{file_digest}\n".encode())
    assert artifact.digest == xxh128_hasher.hexdigest()


def test_manifest_digest_uses_md5_for_md5_artifact():
    f = Path("file.txt")
    f.write_text("hello")
    artifact = Artifact("test", type="dataset", digest_algorithm="MD5")
    artifact.add_file(str(f))

    file_digest = md5_string("hello")
    md5_hasher = _md5(b"wandb-artifact-manifest-v1\n")
    md5_hasher.update(f"file.txt:{file_digest}\n".encode())
    assert artifact.digest == md5_hasher.hexdigest()


def test_entry_digest_algorithm_defaults_to_md5_when_untagged():
    entry = ArtifactManifestEntry(path="file.txt", digest="abc123", size=1)
    assert entry.extra == {}
    assert entry.digest_algorithm() is ArtifactDigestAlgorithm.MANIFEST_MD5


@mark.parametrize(
    ("tag", "expected"),
    [
        ("MD5", ArtifactDigestAlgorithm.MANIFEST_MD5),
        ("XXH128", ArtifactDigestAlgorithm.MANIFEST_XXH128),
        # Unknown/garbage tags fall back to the MD5 default.
        ("bogus", ArtifactDigestAlgorithm.MANIFEST_MD5),
    ],
)
def test_entry_digest_algorithm_reads_extra_tag(tag, expected):
    entry = ArtifactManifestEntry(
        path="file.txt", digest="abc123", size=1, extra={"alg": tag}
    )
    assert entry.digest_algorithm() is expected


def test_add_file_tags_xxh128_entries():
    f = Path("file.txt")
    f.write_text("hello")
    artifact = Artifact("test", type="dataset", digest_algorithm="XXH128")

    entry = artifact.add_file(str(f))

    assert entry.extra == {"alg": "XXH128"}
    assert entry.digest_algorithm() is ArtifactDigestAlgorithm.MANIFEST_XXH128


def test_add_file_leaves_md5_entries_untagged():
    f = Path("file.txt")
    f.write_text("hello")
    artifact = Artifact("test", type="dataset")

    entry = artifact.add_file(str(f))

    # Untagged entries are interpreted as MD5, so we avoid the per-entry bloat.
    assert entry.extra == {}
    assert entry.digest_algorithm() is ArtifactDigestAlgorithm.MANIFEST_MD5


def test_mixed_manifest_round_trip_preserves_per_entry_algorithm():
    from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest

    f = Path("xxh.txt")
    f.write_text("hello")
    artifact = Artifact("test", type="dataset", digest_algorithm="XXH128")
    artifact.add_file(str(f))

    # Simulate an entry carried over untagged from an older (md5) SDK, as
    # happens with `new_draft` across SDK versions.
    artifact.manifest.add_entry(
        ArtifactManifestEntry(path="md5.txt", digest="XUFAKrxLKna5cZ2REBfFkg==", size=5)
    )

    manifest_json = artifact.manifest.to_manifest_json()
    # Only the xxh128 entry is tagged; the untagged md5 entry carries no `extra`.
    assert manifest_json["contents"]["xxh.txt"]["extra"] == {"alg": "XXH128"}
    assert "extra" not in manifest_json["contents"]["md5.txt"]

    restored = ArtifactManifest.from_manifest_json(
        manifest_json, artifact.digest_algorithm
    )
    assert (
        restored.entries["xxh.txt"].digest_algorithm()
        is ArtifactDigestAlgorithm.MANIFEST_XXH128
    )
    assert (
        restored.entries["md5.txt"].digest_algorithm()
        is ArtifactDigestAlgorithm.MANIFEST_MD5
    )


def test_hash_contents_with_md5_correctly_rehashes_xxh128_entries():
    f = Path("file.txt")
    f.write_text("hello")

    f2 = Path("file2.txt")
    f2.write_text("hi")

    artifact = Artifact("test", type="dataset", digest_algorithm="XXH128")
    artifact.add_file(str(f))
    artifact.add_file(str(f2))
    assert (
        artifact.manifest.entries["file.txt"].digest_algorithm()
        is ArtifactDigestAlgorithm.MANIFEST_XXH128
    )
    assert artifact.manifest.entries["file.txt"].digest == xxh128_string("hello")
    assert (
        artifact.manifest.entries["file2.txt"].digest_algorithm()
        is ArtifactDigestAlgorithm.MANIFEST_XXH128
    )
    assert artifact.manifest.entries["file2.txt"].digest == xxh128_string("hi")

    artifact.manifest.hash_contents_with_md5()
    assert artifact.manifest.entries["file.txt"].digest == md5_string("hello")
    assert artifact.manifest.entries["file.txt"].extra == {}
    assert (
        artifact.manifest.entries["file.txt"].digest_algorithm()
        is ArtifactDigestAlgorithm.MANIFEST_MD5
    )
    assert artifact.manifest.entries["file2.txt"].digest == md5_string("hi")
    assert artifact.manifest.entries["file2.txt"].extra == {}
    assert (
        artifact.manifest.entries["file2.txt"].digest_algorithm()
        is ArtifactDigestAlgorithm.MANIFEST_MD5
    )
