"""End-to-end tests for artifact digest algorithm upload, fetch, and fallback.

Run locally against a live backend:

    pytest tests/system_tests/test_artifacts/test_digest_algorithm_e2e.py -vv -s

These tests are skipped when the server does not advertise
``ARTIFACT_DIGEST_ALGORITHM`` support.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import wandb
from pytest import fixture, mark, skip
from wandb import Api, Artifact
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._generated.enums import ArtifactDigestAlgorithm
from wandb.sdk.artifacts._gqlutils import server_supports

pytestmark = [
    # requesting the `user` fixture sets API env var for ALL tests in this module
    mark.usefixtures("user"),
]

# Known digests for a single file containing "hello" (5 bytes).
_HELLO_XXH128_ARTIFACT_DIGEST = "fe0d6c1a25b6d98451da9b04ebf6d80c"
_HELLO_XXH128_FILE_DIGEST = "tenBrQcbPn/Hec+qXlI4GA=="
_HELLO_MD5_ARTIFACT_DIGEST = "a00c2239f036fb656c1dcbf9a32d89b4"
_HELLO_MD5_FILE_DIGEST = "XUFAKrxLKna5cZ2REBfFkg=="


@fixture
def require_digest_algorithm_support(api: Api) -> None:
    if not server_supports(api._service_api, pb.ARTIFACT_DIGEST_ALGORITHM):
        skip("Server does not support ARTIFACT_DIGEST_ALGORITHM")


def _set_digest_algorithm(
    artifact: Artifact, algorithm: ArtifactDigestAlgorithm
) -> None:
    artifact._digest_algorithm = algorithm
    artifact.manifest.digest_algorithm = algorithm


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_xxh128_upload_fetch_and_verify(
    api: Api,
    require_digest_algorithm_support: None,
    tmp_path: Path,
) -> None:
    """New sequence: log with default xxh128, fetch back, download, verify."""
    project = _unique_name("digest-xxh128")
    artifact_name = _unique_name("hello-data")
    file_path = tmp_path / "hello.txt"
    file_path.write_text("hello")

    with wandb.init(project=project) as run:
        artifact = Artifact(artifact_name, "dataset")
        artifact.add_file(str(file_path), name="hello.txt")
        assert artifact.digest_algorithm is ArtifactDigestAlgorithm.MANIFEST_XXH128
        assert artifact.digest == _HELLO_XXH128_ARTIFACT_DIGEST
        run.log_artifact(artifact)

    fetched = api.artifact(f"{project}/{artifact_name}:latest")
    assert fetched.digest_algorithm is ArtifactDigestAlgorithm.MANIFEST_XXH128
    assert fetched.digest == _HELLO_XXH128_ARTIFACT_DIGEST

    entry = fetched.manifest.entries["hello.txt"]
    assert entry.digest == _HELLO_XXH128_FILE_DIGEST

    download_dir = tmp_path / "download"
    fetched.download(root=str(download_dir))
    fetched.verify(root=str(download_dir))

    draft = fetched.new_draft()
    assert draft.digest_algorithm is ArtifactDigestAlgorithm.MANIFEST_XXH128


def test_upload_falls_back_to_md5_for_existing_md5_sequence(
    api: Api,
    require_digest_algorithm_support: None,
    tmp_path: Path,
) -> None:
    """Go saver should downgrade xxh128 -> md5 when the sequence is already MD5."""
    project = _unique_name("digest-fallback")
    artifact_name = _unique_name("mixed-seq")
    file_path = tmp_path / "hello.txt"
    file_path.write_text("hello")

    # v0: establish an MD5 sequence (simulates legacy artifacts).
    with wandb.init(project=project) as run:
        md5_artifact = Artifact(artifact_name, "dataset")
        _set_digest_algorithm(md5_artifact, ArtifactDigestAlgorithm.MANIFEST_MD5)
        md5_artifact.add_file(str(file_path), name="hello.txt")
        assert md5_artifact.digest == _HELLO_MD5_ARTIFACT_DIGEST
        run.log_artifact(md5_artifact, aliases=["v0"])

    # v1: Python defaults to xxh128 locally, but upload should fall back to MD5.
    with wandb.init(project=project) as run:
        xxh_artifact = Artifact(artifact_name, "dataset")
        xxh_artifact.add_file(str(file_path), name="hello.txt")
        assert xxh_artifact.digest_algorithm is ArtifactDigestAlgorithm.MANIFEST_XXH128
        assert xxh_artifact.digest == _HELLO_XXH128_ARTIFACT_DIGEST
        run.log_artifact(xxh_artifact, aliases=["v1"])

    v0 = api.artifact(f"{project}/{artifact_name}:v0")
    v1 = api.artifact(f"{project}/{artifact_name}:v1")

    assert v0.digest_algorithm is ArtifactDigestAlgorithm.MANIFEST_MD5
    assert v0.digest == _HELLO_MD5_ARTIFACT_DIGEST
    assert v0.manifest.entries["hello.txt"].digest == _HELLO_MD5_FILE_DIGEST

    assert v1.digest_algorithm is ArtifactDigestAlgorithm.MANIFEST_MD5
    assert v1.digest == _HELLO_MD5_ARTIFACT_DIGEST
    assert v1.manifest.entries["hello.txt"].digest == _HELLO_MD5_FILE_DIGEST

    download_dir = tmp_path / "v1-download"
    v1.download(root=str(download_dir))
    v1.verify(root=str(download_dir))
