from __future__ import annotations

from pathlib import Path, PurePath
from typing import Any

from pytest import mark, param, raises
from pytest_mock import MockerFixture
from wandb.sdk.artifacts._validators import validate_fspath
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry


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
