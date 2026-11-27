from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import boto3
from moto import mock_aws
from pytest import MonkeyPatch, fixture, mark, raises
from wandb import Artifact

if TYPE_CHECKING:
    from collections.abc import Iterator

    from botocore.client import BaseClient


@fixture
def mock_body() -> bytes:
    """A fixed payload, so an uploaded object's ETag (its MD5) is predictable."""
    return b"0123456789"


@fixture
def expected_etag(mock_body: bytes) -> str:
    """The ETag S3 reports for an object whose body is `mock_body`."""
    return hashlib.md5(mock_body).hexdigest()


@fixture
def artifact() -> Artifact:
    """A test artifact to add references to."""
    return Artifact(type="dataset", name="data-artifact")


@fixture
def aws_credentials(monkeypatch: MonkeyPatch) -> None:
    """Point boto3 at fake credentials so it never reaches real AWS."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("AWS_S3_ENDPOINT_URL", raising=False)


@fixture
def s3(aws_credentials: None) -> Iterator[BaseClient]:
    """An in-memory S3 (via moto) plus a client pointed at it.

    S3Handler builds its own boto3 session the first time `add_reference` hits an
    `s3://` URI. Keeping moto active for the whole test routes that session to
    this in-memory S3 instead of the real one.
    """
    with mock_aws():
        yield boto3.client("s3", region_name="us-east-1")


@fixture
def bucket(s3: BaseClient) -> str:
    """Create an empty, unversioned bucket and return its name."""
    name = "test-bucket"  # Single bucket name shared by all tests
    s3.create_bucket(Bucket=name)
    return name


@fixture
def versioned_bucket(s3: BaseClient, bucket: str) -> str:
    """Create an empty, version-enabled bucket and return its name."""
    s3.put_bucket_versioning(
        Bucket=bucket,
        VersioningConfiguration={"Status": "Enabled"},
    )
    return bucket


def test_add_s3_reference_object(
    s3,
    versioned_bucket,
    mock_body,
    expected_etag,
    artifact,
):
    obj = s3.put_object(Bucket=versioned_bucket, Key="my_object.pb", Body=mock_body)
    version_id = obj["VersionId"]

    artifact.add_reference(f"s3://{versioned_bucket}/my_object.pb")

    assert artifact.manifest.to_manifest_json().get("contents") == {
        "my_object.pb": {
            "digest": expected_etag,
            "ref": f"s3://{versioned_bucket}/my_object.pb",
            "extra": {"etag": expected_etag, "versionID": version_id},
            "size": 10,
        }
    }


def test_add_s3_reference_object_no_version(
    s3,
    bucket,
    mock_body,
    expected_etag,
    artifact,
):
    s3.put_object(Bucket=bucket, Key="my_object.pb", Body=mock_body)

    artifact.add_reference(f"s3://{bucket}/my_object.pb")

    assert artifact.manifest.to_manifest_json().get("contents") == {
        "my_object.pb": {
            "digest": expected_etag,
            "ref": f"s3://{bucket}/my_object.pb",
            "extra": {"etag": expected_etag},
            "size": 10,
        }
    }


def test_add_s3_reference_object_with_version(
    s3,
    versioned_bucket,
    mock_body,
    expected_etag,
    artifact,
):
    obj = s3.put_object(Bucket=versioned_bucket, Key="my_object.pb", Body=mock_body)
    version_id = obj["VersionId"]

    artifact.add_reference(
        f"s3://{versioned_bucket}/my_object.pb?versionId={version_id}"
    )

    assert artifact.manifest.to_manifest_json().get("contents") == {
        "my_object.pb": {
            "digest": expected_etag,
            "ref": f"s3://{versioned_bucket}/my_object.pb",
            "extra": {"etag": expected_etag, "versionID": version_id},
            "size": 10,
        }
    }


def test_add_s3_reference_object_with_name(
    s3,
    versioned_bucket,
    mock_body,
    expected_etag,
    artifact,
):
    obj = s3.put_object(Bucket=versioned_bucket, Key="my_object.pb", Body=mock_body)
    version_id = obj["VersionId"]

    artifact.add_reference(f"s3://{versioned_bucket}/my_object.pb", name="renamed.pb")

    assert artifact.manifest.to_manifest_json().get("contents") == {
        "renamed.pb": {
            "digest": expected_etag,
            "ref": f"s3://{versioned_bucket}/my_object.pb",
            "extra": {"etag": expected_etag, "versionID": version_id},
            "size": 10,
        }
    }


def test_add_s3_reference_object_directory(
    s3,
    bucket,
    mock_body,
    expected_etag,
    artifact,
):
    s3.put_object(Bucket=bucket, Key="my_dir/my_object.pb", Body=mock_body)
    s3.put_object(Bucket=bucket, Key="my_dir/my_other_object.pb", Body=mock_body)

    artifact.add_reference(f"s3://{bucket}/my_dir/")

    assert artifact.manifest.to_manifest_json().get("contents") == {
        "my_object.pb": {
            "digest": expected_etag,
            "ref": f"s3://{bucket}/my_dir/my_object.pb",
            "extra": {"etag": expected_etag},
            "size": 10,
        },
        "my_other_object.pb": {
            "digest": expected_etag,
            "ref": f"s3://{bucket}/my_dir/my_other_object.pb",
            "extra": {"etag": expected_etag},
            "size": 10,
        },
    }


def test_add_s3_reference_path(
    capsys,
    s3,
    bucket,
    mock_body,
    expected_etag,
    artifact,
):
    s3.put_object(Bucket=bucket, Key="my_object.pb", Body=mock_body)
    # A nested key confirms a bucket-root reference recurses into subdirectories.
    s3.put_object(Bucket=bucket, Key="my_dir/my_other_object.pb", Body=mock_body)

    artifact.add_reference(f"s3://{bucket}/")

    assert artifact.manifest.to_manifest_json().get("contents") == {
        "my_object.pb": {
            "digest": expected_etag,
            "ref": f"s3://{bucket}/my_object.pb",
            "extra": {"etag": expected_etag},
            "size": 10,
        },
        "my_dir/my_other_object.pb": {
            "digest": expected_etag,
            "ref": f"s3://{bucket}/my_dir/my_other_object.pb",
            "extra": {"etag": expected_etag},
            "size": 10,
        },
    }

    assert "Generating checksum" in capsys.readouterr().err


def test_add_s3_reference_path_with_content_type(
    capsys,
    s3,
    bucket,
    mock_body,
    expected_etag,
    artifact,
):
    # A zero-byte "directory marker" object: it loads successfully, and its
    # x-directory content type tells the handler to enumerate the prefix.
    s3.put_object(
        Bucket=bucket,
        Key="my_dir",
        Body=b"",
        ContentType="application/x-directory",
    )
    s3.put_object(Bucket=bucket, Key="my_dir/my_object.pb", Body=mock_body)
    s3.put_object(Bucket=bucket, Key="my_dir/my_other_object.pb", Body=mock_body)

    artifact.add_reference(f"s3://{bucket}/my_dir")

    assert artifact.manifest.to_manifest_json().get("contents") == {
        "my_object.pb": {
            "digest": expected_etag,
            "ref": f"s3://{bucket}/my_dir/my_object.pb",
            "extra": {"etag": expected_etag},
            "size": 10,
        },
        "my_other_object.pb": {
            "digest": expected_etag,
            "ref": f"s3://{bucket}/my_dir/my_other_object.pb",
            "extra": {"etag": expected_etag},
            "size": 10,
        },
    }

    assert "Generating checksum" in capsys.readouterr().err


@mark.xfail(
    reason=(
        "S3Handler.store_path fetches only max_objects objects, so an over-limit "
        "reference is silently truncated instead of raising ValueError."
    ),
    strict=True,
)
def test_add_s3_max_objects(s3, bucket, mock_body, artifact):
    s3.put_object(Bucket=bucket, Key="my_dir/my_object.pb", Body=mock_body)
    s3.put_object(Bucket=bucket, Key="my_dir/my_other_object.pb", Body=mock_body)

    with raises(ValueError):
        artifact.add_reference(f"s3://{bucket}/my_dir/", max_objects=1)


def test_add_reference_s3_no_checksum(s3, artifact):
    # No bucket is created: checksum=False records the reference without
    # touching S3, so the bucket need not exist.
    artifact.add_reference("s3://my_bucket/file1.txt", checksum=False)

    assert artifact.manifest.to_manifest_json().get("contents") == {
        "file1.txt": {
            "digest": "s3://my_bucket/file1.txt",
            "ref": "s3://my_bucket/file1.txt",
        }
    }
