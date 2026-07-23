from __future__ import annotations

from pathlib import Path, PurePath
from typing import Any

from pytest import mark, param, raises
from pytest_mock import MockerFixture
from wandb.sdk.artifacts._validators import validate_fspath
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.artifact_manifests.artifact_manifest_v1 import (
    ArtifactManifestV1,
)
from wandb.sdk.lib.hashutil import sha256_file_b64


@mark.parametrize(
    ["kwargs", "expected_repr"],
    [
        param(
            dict(
                path="foo",
                digest="",
                ref="baz",
                birth_artifact_id="qux",
                size=123,
                extra={"quux": "corge"},
                local_path="grault",
            ),
            "ArtifactManifestEntry(path='foo', digest='', ref='baz', birth_artifact_id='qux', size=123, extra={'quux': 'corge'}, local_path='grault', skip_cache=False)",
            id="full",
        ),
        param(
            dict(path="foo", digest="bar", ref="", birth_artifact_id="", size=0),
            "ArtifactManifestEntry(path='foo', digest='bar', ref='', birth_artifact_id='', size=0, skip_cache=False)",
            id="blank",
        ),
        param(
            dict(path="foo", digest="barr"),
            "ArtifactManifestEntry(path='foo', digest='barr', skip_cache=False)",
            id="short",
        ),
    ],
)
def test_manifest_entry_repr(kwargs: dict[str, Any], expected_repr: str):
    entry = ArtifactManifestEntry(**kwargs)
    assert repr(entry) == expected_repr


@mark.parametrize(
    "cache_path",
    [
        param(Path("default_cache"), id="flat-relative-path"),
        param(Path("nested/default_cache"), id="nested-relative-path"),
    ],
)
def test_manifest_download(mocker: MockerFixture, tmp_path: Path, cache_path: Path):
    artifact = Artifact("mnist", type="dataset")
    entry = ArtifactManifestEntry(path="foo", digest="barr")

    # FIXME: Find a way to set up this test without setting private attributes directly
    entry._parent_artifact = artifact

    mocker.patch.object(
        artifact.manifest.storage_policy, "load_reference", return_value=cache_path
    )
    mocker.patch.object(
        artifact.manifest.storage_policy, "load_file", return_value=cache_path
    )

    entry.path = cache_path
    fpath = PurePath(entry.download(root=tmp_path, skip_cache=True))
    assert Path(fpath) == tmp_path / cache_path


def test_manifest_download_rejects_sha256_mismatch(
    mocker: MockerFixture,
    tmp_path: Path,
):
    expected_path = tmp_path / "expected.bin"
    artifact_path = tmp_path / "artifact.bin"
    cache_path = tmp_path / "cache.bin"
    expected_path.write_text("expected")
    artifact_path.write_text("substituted")
    cache_path.write_text("substituted")

    artifact = Artifact("mnist", type="dataset")
    entry = ArtifactManifestEntry(
        path=artifact_path.name,
        digest="legacy-digest",
        extra={"sha256": sha256_file_b64(expected_path)},
    )
    entry._parent_artifact = artifact

    mocker.patch.object(
        artifact.manifest.storage_policy,
        "load_file",
        return_value=cache_path,
    )

    with raises(ValueError, match="Digest mismatch"):
        entry.download(root=tmp_path)


def test_manifest_digest_includes_sha256_when_available(tmp_path: Path):
    first_manifest = ArtifactManifestV1()
    first_manifest.add_entry(
        ArtifactManifestEntry(
            path="artifact.bin",
            digest="legacy-digest",
            extra={"sha256": "first-sha256"},
        )
    )
    second_manifest = ArtifactManifestV1()
    second_manifest.add_entry(
        ArtifactManifestEntry(
            path="artifact.bin",
            digest="legacy-digest",
            extra={"sha256": "second-sha256"},
        )
    )

    assert first_manifest.digest() != second_manifest.digest()


@mark.parametrize(
    "entry_path",
    [
        param("default_cache", id="flat-relative-path"),
        param("nested/default_cache", id="nested-relative-path"),
    ],
)
def test_validate_fspath_on_manifest_entry_path(tmp_path, entry_path):
    entry = ArtifactManifestEntry(path=entry_path, digest="barr")

    assert Path(validate_fspath(tmp_path, entry.path)) == tmp_path / entry_path


@mark.parametrize(
    "invalid_path",
    [
        "../outside.txt",  # Relative path via parent directory traversal.
        "/outside.txt",  # Absolute path from the POSIX root.
        "C:\\outside.txt",  # Absolute path from a Windows drive root.
    ],
)
def test_manifest_download_rejects_invalid_path(mocker, tmp_path, invalid_path):
    artifact = Artifact("mnist", type="dataset")
    entry = ArtifactManifestEntry(path=invalid_path, digest="barr")

    # FIXME: Find a way to set up this test without setting private attributes directly
    entry._parent_artifact = artifact

    load_file_spy = mocker.spy(artifact.manifest.storage_policy, "load_file")

    with raises(ValueError, match="Invalid artifact path"):
        entry.download(root=tmp_path, skip_cache=True)

    load_file_spy.assert_not_called()
