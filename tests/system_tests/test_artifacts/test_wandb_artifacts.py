import filecmp
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from typing import Iterator, Mapping, Optional
from urllib.parse import quote

import numpy as np
import pytest
import requests
import responses
from pytest_mock import MockerFixture

import wandb
import wandb.data_types as data_types
import wandb.sdk.artifacts.artifact_file_cache as artifact_file_cache
import wandb.sdk.internal.sender
from wandb import Artifact, util
from wandb.errors.errors import CommError
from wandb.sdk.artifacts._internal_artifact import InternalArtifact
from wandb.sdk.artifacts._validators import (
    ARTIFACT_NAME_MAXLEN,
    RESERVED_ARTIFACT_TYPE_PREFIX,
)
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.artifact_state import ArtifactState
from wandb.sdk.artifacts.artifact_ttl import ArtifactTTL
from wandb.sdk.artifacts.exceptions import (
    ArtifactFinalizedError,
    ArtifactNotLoggedError,
)
from wandb.sdk.artifacts.storage_handlers.gcs_handler import (
    GCSHandler,
    _GCSIsADirectoryError,
)
from wandb.sdk.artifacts.storage_handlers.http_handler import HTTPHandler
from wandb.sdk.artifacts.storage_handlers.s3_handler import S3Handler
from wandb.sdk.artifacts.storage_handlers.tracking_handler import TrackingHandler
from wandb.sdk.lib.hashutil import md5_string


def mock_boto(artifact, path=False, content_type=None, version_id="1"):
    class S3Object:
        def __init__(self, name="my_object.pb", metadata=None, version_id=version_id):
            self.metadata = metadata or {"md5": "1234567890abcde"}
            self.e_tag = '"1234567890abcde"'
            self.bucket_name = "my-bucket"
            self.version_id = version_id
            self.name = name
            self.key = name
            self.content_length = 10
            self.content_type = (
                "application/pb; charset=UTF-8"
                if content_type is None
                else content_type
            )

        def load(self):
            if path:
                raise util.get_module("botocore").exceptions.ClientError(
                    {
                        "Error": {"Code": "404"},
                    },
                    "HeadObject",
                )

    class S3ObjectSummary:
        def __init__(self, name=None, size=10):
            self.e_tag = '"1234567890abcde"'
            self.bucket_name = "my-bucket"
            self.key = name or "my_object.pb"
            self.size = size

    class Filtered:
        def limit(self, *args, **kwargs):
            return [S3ObjectSummary(), S3ObjectSummary(name="my_other_object.pb")]

    class S3Objects:
        def filter(self, **kwargs):
            return Filtered()

        def limit(self, *args, **kwargs):
            return [S3ObjectSummary(), S3ObjectSummary(name="my_other_object.pb")]

    class S3Bucket:
        def __init__(self, *args, **kwargs):
            self.objects = S3Objects()

    class S3Resource:
        def Object(self, bucket, key):  # noqa: N802
            return S3Object(name=key)

        def ObjectVersion(self, bucket, key, version):  # noqa: N802
            class Version:
                def Object(self):  # noqa: N802
                    return S3Object(version_id=version)

            return Version()

        def Bucket(self, bucket):  # noqa: N802
            return S3Bucket()

        def BucketVersioning(self, bucket):  # noqa: N802
            class BucketStatus:
                status = "Enabled"

            return BucketStatus()

    mock = S3Resource()
    for handler in artifact.manifest.storage_policy._handler._handlers:
        if isinstance(handler, S3Handler):
            handler._s3 = mock
            handler._botocore = util.get_module("botocore")
            handler._botocore.exceptions = util.get_module("botocore.exceptions")
    return mock


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
            return [Blob(), Blob(name="my_other_object.pb")]

    class GSClient:
        def bucket(self, bucket):
            return GSBucket()

    mock = GSClient()
    for handler in artifact.manifest.storage_policy._handler._handlers:
        if isinstance(handler, GCSHandler):
            handler._client = mock
    return mock


@pytest.fixture
def mock_azure_handler(mocker: MockerFixture):
    class BlobServiceClient:
        def __init__(self, account_url, credential):
            pass

        def get_container_client(self, container):
            return ContainerClient()

        def get_blob_client(self, container, blob):
            return BlobClient(blob)

    class ContainerClient:
        def list_blobs(self, name_starts_with):
            return [
                blob_properties
                for blob_properties in blobs
                if blob_properties.name.startswith(name_starts_with)
            ]

    class BlobClient:
        def __init__(self, name):
            self.name = name

        def exists(self, version_id=None):
            for blob_properties in blobs:
                if (
                    blob_properties.name == self.name
                    and blob_properties.version_id == version_id
                ):
                    return True
            return False

        def get_blob_properties(self, version_id=None):
            for blob_properties in blobs:
                if (
                    blob_properties.name == self.name
                    and blob_properties.version_id == version_id
                ):
                    return blob_properties
            raise Exception("Blob does not exist")

    # Use the real `azure.storage.blob.BlobProperties` class
    from azure.storage.blob import BlobProperties
    # NOTE: BlobProperties converts the following variadic keyword args -> attribute names:
    # - name -> name
    # - x-ms-version-id -> version_id
    # - ETag -> etag
    # - Content-Length -> size
    # - metadata -> metadata

    blobs = [
        BlobProperties(
            **{
                "name": "my-blob",
                "x-ms-version-id": None,
                "ETag": "my-blob version None",
                "Content-Length": 42,
                "metadata": {},
            },
        ),
        BlobProperties(
            **{
                "name": "my-blob",
                "x-ms-version-id": "v2",
                "ETag": "my-blob version v2",
                "Content-Length": 42,
                "metadata": {},
            },
        ),
        BlobProperties(
            **{
                "name": "my-dir/a",
                "x-ms-version-id": None,
                "ETag": "my-dir/a version None",
                "Content-Length": 42,
                "metadata": {},
            },
        ),
        BlobProperties(
            **{
                "name": "my-dir/b",
                "x-ms-version-id": None,
                "ETag": "my-dir/b version None",
                "Content-Length": 42,
                "metadata": {},
            },
        ),
        BlobProperties(
            **{
                "name": "my-dir",
                "x-ms-version-id": None,
                "ETag": "my-dir version None",
                "Content-Length": 0,
                "metadata": {"hdi_isfolder": "true"},
            },
        ),
    ]

    mocked_azure_modules = {
        "azure.storage.blob": SimpleNamespace(
            BlobServiceClient=BlobServiceClient,
        ),
        "azure.identity": SimpleNamespace(
            DefaultAzureCredential=lambda: None,
        ),
    }

    # For the duration of the test, mock the imported azure modules
    mocker.patch.dict(sys.modules, mocked_azure_modules)

    yield


def mock_http(artifact, path=False, headers=None):
    headers = headers or {}

    class Response:
        def __init__(self, headers):
            self.headers = headers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def raise_for_status(self):
            pass

    class Session:
        def __init__(self, name="file1.txt", headers=headers):
            self.headers = headers

        def get(self, path, *args, **kwargs):
            return Response(self.headers)

    mock = Session()
    for handler in artifact.manifest.storage_policy._handler._handlers:
        if isinstance(handler, HTTPHandler):
            handler._session = mock
    return mock


@pytest.fixture
def artifact() -> Artifact:
    return Artifact(type="dataset", name="data-artifact")


def test_unsized_manifest_entry_real_file():
    f = Path("some/file.txt")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("hello")
    entry = ArtifactManifestEntry(path="foo", digest="123", local_path="some/file.txt")
    assert entry.size == 5


def test_unsized_manifest_entry():
    with pytest.raises(FileNotFoundError) as e:
        ArtifactManifestEntry(path="foo", digest="123", local_path="some/file.txt")
    assert "No such file" in str(e.value)


def test_add_one_file(artifact):
    Path("file1.txt").write_text("hello")
    artifact.add_file("file1.txt")

    assert artifact.digest == "a00c2239f036fb656c1dcbf9a32d89b4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "size": 5,
    }


def test_add_named_file(artifact):
    Path("file1.txt").write_text("hello")
    artifact.add_file("file1.txt", name="great-file.txt")

    assert artifact.digest == "585b9ada17797e37c9cbab391e69b8c5"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["great-file.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "size": 5,
    }


def test_add_new_file(artifact):
    with artifact.new_file("file1.txt") as f:
        f.write("hello")

    assert artifact.digest == "a00c2239f036fb656c1dcbf9a32d89b4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "size": 5,
    }


def test_add_after_finalize(artifact):
    artifact.finalize()
    with pytest.raises(ArtifactFinalizedError) as e:
        artifact.add_file("file1.txt")
    assert "Can't modify finalized artifact" in str(e.value)


def test_add_new_file_encode_error(capsys, artifact):
    with pytest.raises(UnicodeEncodeError):
        with artifact.new_file("wave.txt", mode="w", encoding="ascii") as f:
            f.write("∂²u/∂t²=c²·∂²u/∂x²")
    assert "ERROR Failed to open the provided file" in capsys.readouterr().err


@pytest.mark.parametrize("overwrite", [True, False])
def test_add_file_again_after_edit(overwrite, artifact):
    filepath = Path("file1.txt")

    filepath.write_text("hello")
    artifact.add_file(str(filepath), overwrite=overwrite)

    # If we explicitly pass overwrite=True, allow rewriting an existing file
    filepath.write_text("Potato")
    expectation = nullcontext() if overwrite else pytest.raises(ValueError)
    with expectation:
        artifact.add_file(str(filepath), overwrite=overwrite)


def test_add_dir(artifact):
    Path("file1.txt").write_text("hello")

    artifact.add_dir(".")

    assert artifact.digest == "a00c2239f036fb656c1dcbf9a32d89b4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "size": 5,
    }


def test_add_named_dir(artifact):
    Path("file1.txt").write_text("hello")
    artifact.add_dir(".", name="subdir")

    assert artifact.digest == "a757208d042e8627b2970d72a71bed5b"

    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["subdir/file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "size": 5,
    }


@pytest.mark.parametrize("merge", [True, False])
def test_add_dir_again_after_edit(merge, artifact, tmp_path_factory):
    rootdir = tmp_path_factory.mktemp("test-dir", numbered=True)

    file_changed = rootdir / "file1.txt"
    file_changed.write_text("will be updated")

    file_not_changed = rootdir / "file2.txt"
    file_not_changed.write_text("something never changes")

    artifact.add_dir(str(rootdir))

    # If we explicitly pass overwrite=True, allow rewriting an existing file in dir
    file_changed.write_text("this is the update")
    expectation = nullcontext() if merge else pytest.raises(ValueError)
    with expectation:
        artifact.add_dir(rootdir, merge=merge)
        # make sure we have two files
        assert len(artifact.manifest.to_manifest_json()["contents"]) == 2

    # Delete the file, call add_dir again, regardless of merge, we still have the files
    # we already added because of the mutable policy copy the files.
    file_changed.unlink()
    artifact.add_dir(rootdir, merge=merge)
    assert len(artifact.manifest.to_manifest_json()["contents"]) == 2


def test_multi_add(artifact):
    size = 2**27  # 128MB, large enough that it takes >1ms to add.
    filename = "data.bin"
    with open(filename, "wb") as f:
        f.truncate(size)

    # Add 8 copies simultaneously.
    with ThreadPoolExecutor(max_workers=8) as e:
        for _ in range(8):
            e.submit(lambda: artifact.add_file(filename))

    # There should be only one file in the artifact.
    manifest = artifact.manifest.to_manifest_json()
    assert len(manifest["contents"]) == 1
    assert manifest["contents"][filename]["size"] == size


def test_add_reference_local_file(tmp_path, artifact):
    file = tmp_path / "file1.txt"
    file.write_text("hello")
    uri = file.as_uri()

    e = artifact.add_reference(uri)[0]
    assert e.ref_target() == uri

    assert artifact.digest == "a00c2239f036fb656c1dcbf9a32d89b4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "ref": uri,
        "size": 5,
    }


def test_add_reference_local_file_no_checksum(tmp_path, artifact):
    file = tmp_path / "file1.txt"
    file.write_text("hello")
    uri = file.as_uri()

    size = os.path.getsize(file)
    artifact.add_reference(uri, checksum=False)

    expected_entry_digest = md5_string(uri)

    # With checksum=False, the artifact digest will depend on its files'
    # absolute paths.  The working test directory isn't fixed from run
    # to run, so there isn't much benefit in asserting on the exact hash here.
    # The following are just some basic consistency/sanity checks.
    assert isinstance(artifact.digest, str)
    assert len(artifact.digest) == 32
    assert int(artifact.digest, 16) != 0  # nonzero hexadecimal literal

    assert artifact.digest != expected_entry_digest

    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": expected_entry_digest,
        "ref": uri,
        "size": size,
    }


class TestAddReferenceLocalFileNoChecksumTwice:
    @pytest.fixture
    def run(self, user) -> Iterator[wandb.Run]:
        with wandb.init() as run:
            yield run

    @pytest.fixture
    def orig_data(self) -> str:
        """The contents of the original file."""
        return "hello"

    @pytest.fixture
    def orig_fpath(self, tmp_path_factory) -> Path:
        """The path to the original file."""
        # Use a factory to generate unique filepaths per test
        return tmp_path_factory.mktemp("orig_path") / "file1.txt"

    @pytest.fixture
    def orig_artifact(self, orig_fpath, orig_data, artifact, run) -> Artifact:
        """The original, logged artifact in the sequence collection."""
        file_path = orig_fpath
        file_path.write_text(orig_data)

        # Create the reference artifact and log it while bypassing the checksum
        artifact.add_reference(file_path.as_uri(), checksum=False)
        logged_artifact = run.log_artifact(artifact)
        logged_artifact.wait()

        # Assumption/consistency check
        assert logged_artifact.version == "v0"

        return logged_artifact

    @pytest.fixture
    def new_data(self) -> str:
        """The contents of the new file."""
        return "goodbye"

    @pytest.fixture
    def new_fpath(self, tmp_path_factory) -> Path:
        """The path to the new file."""
        return tmp_path_factory.mktemp("new_path") / "file2.txt"

    @pytest.fixture
    def new_artifact(self, orig_artifact) -> Artifact:
        """A new artifact with the same name and type, but not yet logged."""
        return wandb.Artifact(orig_artifact.name.split(":")[0], type=orig_artifact.type)

    def test_adding_ref_with_same_uri_and_same_data_creates_no_new_version(
        self, run, orig_fpath, orig_data, orig_artifact, new_artifact
    ):
        fpath = orig_fpath
        fpath.write_text(orig_data)

        # Create the second reference artifact and log it
        new_artifact.add_reference(fpath.as_uri(), checksum=False)
        new_artifact = run.log_artifact(new_artifact)
        new_artifact.wait()

        assert new_artifact.version == orig_artifact.version

    def test_adding_ref_with_same_uri_and_new_data_creates_no_new_version(
        self, run, orig_fpath, new_data, orig_artifact, new_artifact
    ):
        # Keep the original filepath, but overwrite its contents
        fpath = orig_fpath
        fpath.write_text(new_data)

        # Create the second reference artifact and log it
        new_artifact.add_reference(fpath.as_uri(), checksum=False)
        new_artifact = run.log_artifact(new_artifact)
        new_artifact.wait()

        assert new_artifact.version == orig_artifact.version

    def test_adding_ref_with_new_uri_and_same_data_creates_new_version(
        self, run, new_fpath, orig_data, orig_artifact, new_artifact
    ):
        # Keep the original filepath, but overwrite its contents
        fpath = new_fpath
        fpath.write_text(orig_data)

        # Create the second reference artifact and log it
        new_artifact.add_reference(fpath.as_uri(), checksum=False)
        new_artifact = run.log_artifact(new_artifact)
        new_artifact.wait()

        assert new_artifact.version != orig_artifact.version

    def test_adding_ref_with_new_uri_and_new_data_creates_new_version(
        self, run, new_fpath, new_data, orig_artifact, new_artifact
    ):
        fpath = new_fpath
        fpath.write_text(new_data)

        # Create the second reference artifact and log it
        new_artifact.add_reference(fpath.as_uri(), checksum=False)
        new_artifact = run.log_artifact(new_artifact)
        new_artifact.wait()

        assert new_artifact.version != orig_artifact.version


def test_add_reference_local_dir(artifact):
    Path("file1.txt").write_text("hello")
    os.mkdir("nest")
    Path("nest/file2.txt").write_text("my")
    os.mkdir("nest/nest")
    Path("nest/nest/file3.txt").write_text("dude")

    artifact.add_reference(f"file://{os.getcwd()}")

    assert artifact.digest == "72414374bfd4b0f60a116e7267845f71"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "ref": "file://" + os.path.join(os.getcwd(), "file1.txt"),
        "size": 5,
    }
    assert manifest["contents"]["nest/file2.txt"] == {
        "digest": "aGTzidmHZDa8h3j/Bx0bbA==",
        "ref": "file://" + os.path.join(os.getcwd(), "nest", "file2.txt"),
        "size": 2,
    }
    assert manifest["contents"]["nest/nest/file3.txt"] == {
        "digest": "E7c+2uhEOZC+GqjxpIO8Jw==",
        "ref": "file://" + os.path.join(os.getcwd(), "nest", "nest", "file3.txt"),
        "size": 4,
    }


def test_add_reference_local_dir_no_checksum(artifact):
    path_1 = Path("file1.txt")
    path_1.parent.mkdir(parents=True, exist_ok=True)
    path_1.write_text("hello")
    size_1 = path_1.stat().st_size
    uri_1 = path_1.resolve().as_uri()

    path_2 = Path("nest/file2.txt")
    path_2.parent.mkdir(parents=True, exist_ok=True)
    path_2.write_text("my")
    size_2 = path_2.stat().st_size
    uri_2 = path_2.resolve().as_uri()

    path_3 = Path("nest", "nest", "file3.txt")
    path_3.parent.mkdir(parents=True, exist_ok=True)
    path_3.write_text("dude")
    size_3 = path_3.stat().st_size
    uri_3 = path_3.resolve().as_uri()

    here = Path.cwd()
    root_uri = here.resolve().as_uri()
    artifact.add_reference(root_uri, checksum=False)

    expected_entry_digest_1 = md5_string(uri_1)
    expected_entry_digest_2 = md5_string(uri_2)
    expected_entry_digest_3 = md5_string(uri_3)

    # With checksum=False, the artifact digest will depend on its files'
    # absolute paths.  The working test directory isn't fixed from run
    # to run, so there isn't much benefit in asserting on the exact hash here.
    # The following are just some basic consistency/sanity checks.
    assert isinstance(artifact.digest, str)
    assert len(artifact.digest) == 32
    assert int(artifact.digest, 16) != 0  # nonzero hexadecimal literal

    assert artifact.digest != expected_entry_digest_1
    assert artifact.digest != expected_entry_digest_2
    assert artifact.digest != expected_entry_digest_3

    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": expected_entry_digest_1,
        "ref": uri_1,
        "size": size_1,
    }
    assert manifest["contents"]["nest/file2.txt"] == {
        "digest": expected_entry_digest_2,
        "ref": uri_2,
        "size": size_2,
    }
    assert manifest["contents"]["nest/nest/file3.txt"] == {
        "digest": expected_entry_digest_3,
        "ref": uri_3,
        "size": size_3,
    }


def test_add_reference_local_dir_with_name(artifact):
    Path("file1.txt").write_text("hello")
    Path("nest").mkdir(parents=True, exist_ok=True)
    Path("nest/file2.txt").write_text("my")
    Path("nest/nest").mkdir(parents=True, exist_ok=True)
    Path("nest/nest/file3.txt").write_text("dude")

    here = Path.cwd()
    artifact.add_reference(f"file://{here!s}", name="top")

    assert artifact.digest == "f718baf2d4c910dc6ccd0d9c586fa00f"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["top/file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "ref": f"file://{here!s}/file1.txt",
        "size": 5,
    }
    assert manifest["contents"]["top/nest/file2.txt"] == {
        "digest": "aGTzidmHZDa8h3j/Bx0bbA==",
        "ref": f"file://{here!s}/nest/file2.txt",
        "size": 2,
    }
    assert manifest["contents"]["top/nest/nest/file3.txt"] == {
        "digest": "E7c+2uhEOZC+GqjxpIO8Jw==",
        "ref": f"file://{here!s}/nest/nest/file3.txt",
        "size": 4,
    }


def test_add_reference_local_dir_by_uri(tmp_path, artifact):
    ugly_path = tmp_path / "i=D" / "has !@#$%^&[]()|',`~ awful taste in file names"
    ugly_path.mkdir(parents=True)
    file = ugly_path / "file.txt"
    file.write_text("sorry")

    artifact.add_reference(ugly_path.as_uri())
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file.txt"] == {
        "digest": "c88OOIlx7k7DTo2u3Q02zA==",
        "ref": file.as_uri(),
        "size": 5,
    }


def test_add_s3_reference_object(artifact):
    mock_boto(artifact)
    artifact.add_reference("s3://my-bucket/my_object.pb")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["my_object.pb"] == {
        "digest": "1234567890abcde",
        "ref": "s3://my-bucket/my_object.pb",
        "extra": {"etag": "1234567890abcde", "versionID": "1"},
        "size": 10,
    }


def test_add_s3_reference_object_directory(artifact):
    mock_boto(artifact, path=True)
    artifact.add_reference("s3://my-bucket/my_dir/")

    assert artifact.digest == "17955d00a20e1074c3bc96c74b724bfe"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["my_object.pb"] == {
        "digest": "1234567890abcde",
        "ref": "s3://my-bucket/my_dir",
        "extra": {"etag": "1234567890abcde", "versionID": "1"},
        "size": 10,
    }


def test_add_s3_reference_object_no_version(artifact):
    mock_boto(artifact, version_id=None)
    artifact.add_reference("s3://my-bucket/my_object.pb")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["my_object.pb"] == {
        "digest": "1234567890abcde",
        "ref": "s3://my-bucket/my_object.pb",
        "extra": {"etag": "1234567890abcde"},
        "size": 10,
    }


def test_add_s3_reference_object_with_version(artifact):
    mock_boto(artifact)
    artifact.add_reference("s3://my-bucket/my_object.pb?versionId=2")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["my_object.pb"] == {
        "digest": "1234567890abcde",
        "ref": "s3://my-bucket/my_object.pb",
        "extra": {"etag": "1234567890abcde", "versionID": "2"},
        "size": 10,
    }


def test_add_s3_reference_object_with_name(artifact):
    mock_boto(artifact)
    artifact.add_reference("s3://my-bucket/my_object.pb", name="renamed.pb")

    assert artifact.digest == "bd85fe009dc9e408a5ed9b55c95f47b2"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["renamed.pb"] == {
        "digest": "1234567890abcde",
        "ref": "s3://my-bucket/my_object.pb",
        "extra": {"etag": "1234567890abcde", "versionID": "1"},
        "size": 10,
    }


def test_add_s3_reference_path(runner, capsys, artifact):
    mock_boto(artifact, path=True)
    artifact.add_reference("s3://my-bucket/")

    assert artifact.digest == "17955d00a20e1074c3bc96c74b724bfe"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["my_object.pb"] == {
        "digest": "1234567890abcde",
        "ref": "s3://my-bucket/my_object.pb",
        "extra": {"etag": "1234567890abcde", "versionID": "1"},
        "size": 10,
    }
    _, err = capsys.readouterr()
    assert "Generating checksum" in err


def test_add_s3_reference_path_with_content_type(runner, capsys, artifact):
    with runner.isolated_filesystem():
        mock_boto(artifact, path=False, content_type="application/x-directory")
        artifact.add_reference("s3://my-bucket/my_dir")

        assert artifact.digest == "17955d00a20e1074c3bc96c74b724bfe"
        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"]["my_object.pb"] == {
            "digest": "1234567890abcde",
            "ref": "s3://my-bucket/my_dir",
            "extra": {"etag": "1234567890abcde", "versionID": "1"},
            "size": 10,
        }
        _, err = capsys.readouterr()
        assert "Generating checksum" in err


def test_add_s3_max_objects(artifact):
    mock_boto(artifact, path=True)
    with pytest.raises(ValueError):
        artifact.add_reference("s3://my-bucket/", max_objects=1)


def test_add_reference_s3_no_checksum(artifact):
    Path("file1.txt").write_text("hello")
    mock_boto(artifact)
    # TODO: Should we require name in this case?
    artifact.add_reference("s3://my_bucket/file1.txt", checksum=False)

    assert artifact.digest == "52631787ed3579325f985dc0f2374040"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": "s3://my_bucket/file1.txt",
        "ref": "s3://my_bucket/file1.txt",
    }


def test_add_gs_reference_object(artifact):
    mock_gcs(artifact)
    artifact.add_reference("gs://my-bucket/my_object.pb")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["my_object.pb"] == {
        "digest": "1234567890abcde",
        "ref": "gs://my-bucket/my_object.pb",
        "extra": {"versionID": "1"},
        "size": 10,
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

    with pytest.raises(ValueError, match="Digest mismatch"):
        entry.download()


def test_add_gs_reference_object_with_version(artifact):
    mock_gcs(artifact)
    artifact.add_reference("gs://my-bucket/my_object.pb#2")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["my_object.pb"] == {
        "digest": "1234567890abcde",
        "ref": "gs://my-bucket/my_object.pb",
        "extra": {"versionID": "2"},
        "size": 10,
    }


def test_add_gs_reference_object_with_name(artifact):
    mock_gcs(artifact)
    artifact.add_reference("gs://my-bucket/my_object.pb", name="renamed.pb")

    assert artifact.digest == "bd85fe009dc9e408a5ed9b55c95f47b2"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["renamed.pb"] == {
        "digest": "1234567890abcde",
        "ref": "gs://my-bucket/my_object.pb",
        "extra": {"versionID": "1"},
        "size": 10,
    }


def test_add_gs_reference_path(runner, capsys, artifact):
    with runner.isolated_filesystem():
        mock_gcs(artifact, path=True)
        artifact.add_reference("gs://my-bucket/")

        assert artifact.digest == "17955d00a20e1074c3bc96c74b724bfe"
        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"]["my_object.pb"] == {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_object.pb",
            "extra": {"versionID": "1"},
            "size": 10,
        }
        _, err = capsys.readouterr()
        assert "Generating checksum" in err


def test_add_gs_reference_object_no_md5(artifact):
    mock_gcs(artifact, hash=False)
    artifact.add_reference("gs://my-bucket/my_object.pb")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["my_object.pb"] == {
        "digest": "1234567890abcde",
        "ref": "gs://my-bucket/my_object.pb",
        "extra": {"versionID": "1"},
        "size": 10,
    }


def test_add_gs_reference_with_dir_paths(artifact):
    mock_gcs(artifact, override_blob_name="my_folder/")
    artifact.add_reference("gs://my-bucket/my_folder/")

    assert len(artifact.manifest.entries) == 0


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
    with pytest.raises(_GCSIsADirectoryError):
        gcs_handler.load_path(simple_entry, local=True)

    # case where we didn't store "/" and have to use get_blob
    entry = ArtifactManifestEntry(
        path="my-bucket/my_folder",
        ref="gs://my-bucket/my_folder",
        digest="1234567890abcde",
        size=0,
        extra={"versionID": 1},
    )
    with pytest.raises(_GCSIsADirectoryError):
        gcs_handler.load_path(entry, local=True)


@pytest.fixture
def my_artifact() -> Artifact:
    """A test artifact with a custom type."""
    return Artifact("my_artifact", type="my_type")


@pytest.mark.parametrize("name", [None, "my-name"])
@pytest.mark.parametrize("version_id", [None, "v2"])
def test_add_azure_reference_no_checksum(
    mock_azure_handler, my_artifact, name, version_id
):
    uri = "https://myaccount.blob.core.windows.net/my-container/nonexistent-blob"

    if version_id and name:
        entries = my_artifact.add_reference(
            f"{uri}?versionId={version_id}", name=name, checksum=False
        )
    elif version_id and not name:
        entries = my_artifact.add_reference(
            f"{uri}?versionId={version_id}", checksum=False
        )
    elif (not version_id) and name:
        entries = my_artifact.add_reference(uri, name=name, checksum=False)
    else:
        entries = my_artifact.add_reference(uri, checksum=False)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.path == "nonexistent-blob" if (name is None) else name
    assert entry.ref == uri
    assert entry.digest == uri
    assert entry.size is None
    assert entry.extra == {}


@pytest.mark.parametrize("name", [None, "my-name"])
@pytest.mark.parametrize("version_id", [None, "v2"])
def test_add_azure_reference(mock_azure_handler, my_artifact, name, version_id):
    uri = "https://myaccount.blob.core.windows.net/my-container/my-blob"

    if version_id and name:
        entries = my_artifact.add_reference(f"{uri}?versionId={version_id}", name=name)
    elif version_id and not name:
        entries = my_artifact.add_reference(f"{uri}?versionId={version_id}")
    elif (not version_id) and name:
        entries = my_artifact.add_reference(uri, name=name)
    else:
        entries = my_artifact.add_reference(uri)

    assert len(entries) == 1
    entry = entries[0]

    if name is None:
        assert entry.path == "my-blob"
    else:
        assert entry.path == name

    if version_id is None:
        assert entry.digest == "my-blob version None"
        assert entry.extra == {"etag": "my-blob version None"}
    else:
        assert entry.digest == f"my-blob version {version_id}"
        assert entry.extra == {
            "etag": f"my-blob version {version_id}",
            "versionID": version_id,
        }

    assert entry.ref == uri
    assert entry.size == 42


def test_add_azure_reference_directory(mock_azure_handler):
    artifact = Artifact("my_artifact", type="my_type")
    entries = artifact.add_reference(
        "https://myaccount.blob.core.windows.net/my-container/my-dir"
    )
    assert len(entries) == 2
    assert entries[0].path == "a"
    assert (
        entries[0].ref
        == "https://myaccount.blob.core.windows.net/my-container/my-dir/a"
    )
    assert entries[0].digest == "my-dir/a version None"
    assert entries[0].size == 42
    assert entries[0].extra == {"etag": "my-dir/a version None"}
    assert entries[1].path == "b"
    assert (
        entries[1].ref
        == "https://myaccount.blob.core.windows.net/my-container/my-dir/b"
    )
    assert entries[1].digest == "my-dir/b version None"
    assert entries[1].size == 42
    assert entries[1].extra == {"etag": "my-dir/b version None"}

    # with name
    artifact = Artifact("my_artifact", type="my_type")
    entries = artifact.add_reference(
        "https://myaccount.blob.core.windows.net/my-container/my-dir", name="my-name"
    )
    assert len(entries) == 2
    assert entries[0].path == "my-name/a"
    assert (
        entries[0].ref
        == "https://myaccount.blob.core.windows.net/my-container/my-dir/a"
    )
    assert entries[0].digest == "my-dir/a version None"
    assert entries[0].size == 42
    assert entries[0].extra == {"etag": "my-dir/a version None"}
    assert entries[1].path == "my-name/b"
    assert (
        entries[1].ref
        == "https://myaccount.blob.core.windows.net/my-container/my-dir/b"
    )
    assert entries[1].digest == "my-dir/b version None"
    assert entries[1].size == 42
    assert entries[1].extra == {"etag": "my-dir/b version None"}


def test_add_azure_reference_max_objects(mock_azure_handler):
    artifact = wandb.Artifact("my_artifact", type="my_type")
    entries = artifact.add_reference(
        "https://myaccount.blob.core.windows.net/my-container/my-dir",
        max_objects=1,
    )
    assert len(entries) == 1
    assert entries[0].path == "a" or entries[0].path == "b"
    if entries[0].path == "a":
        assert (
            entries[0].ref
            == "https://myaccount.blob.core.windows.net/my-container/my-dir/a"
        )
        assert entries[0].digest == "my-dir/a version None"
        assert entries[0].size == 42
        assert entries[0].extra == {"etag": "my-dir/a version None"}
    else:
        assert (
            entries[1].ref
            == "https://myaccount.blob.core.windows.net/my-container/my-dir/b"
        )
        assert entries[1].digest == "my-dir/b version None"
        assert entries[1].size == 42
        assert entries[1].extra == {"etag": "my-dir/b version None"}


def test_add_http_reference_path(artifact):
    mock_http(
        artifact,
        headers={
            "ETag": '"abc"',
            "Content-Length": "256",
        },
    )
    artifact.add_reference("http://example.com/file1.txt")

    assert artifact.digest == "48237ccc050a88af9dcd869dd5a7e9f4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": "abc",
        "ref": "http://example.com/file1.txt",
        "size": 256,
        "extra": {
            "etag": '"abc"',
        },
    }


def test_add_reference_named_local_file(tmp_path, artifact):
    file = tmp_path / "file1.txt"
    file.write_text("hello")
    uri = file.as_uri()

    artifact.add_reference(uri, name="great-file.txt")

    assert artifact.digest == "585b9ada17797e37c9cbab391e69b8c5"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["great-file.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "ref": uri,
        "size": 5,
    }


def test_add_reference_unknown_handler(artifact):
    artifact.add_reference("ref://example.com/somefile.txt", name="ref")

    assert artifact.digest == "410ade94865e89ebe1f593f4379ac228"

    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["ref"] == {
        "digest": "ref://example.com/somefile.txt",
        "ref": "ref://example.com/somefile.txt",
    }


@pytest.mark.parametrize("name_type", [str, Path, PurePosixPath, PureWindowsPath])
def test_remove_file(name_type, artifact):
    file1 = Path("file1.txt")
    file1.parent.mkdir(parents=True, exist_ok=True)
    file1.write_text("hello")
    file2 = Path("file2.txt")
    file2.write_text("hello")

    artifact.add_file(file1)
    artifact.add_file(file2, name="renamed.txt")

    artifact.remove(name_type(file1))
    artifact.remove(name_type("renamed.txt"))

    assert artifact.manifest.entries == {}


@pytest.mark.parametrize("name_type", [str, Path, PurePosixPath, PureWindowsPath])
def test_remove_directory(name_type, artifact):
    file1 = Path("bar/foo/file1.txt")
    file1.parent.mkdir(parents=True, exist_ok=True)
    file1.write_text("hello")
    file2 = Path("bar/foo/file2.txt")
    file2.write_text("hello2")

    artifact.add_dir("bar")

    assert len(artifact.manifest.entries) == 2

    artifact.remove(name_type("foo"))

    assert artifact.manifest.entries == {}


def test_remove_non_existent(artifact):
    file1 = Path("baz/foo/file1.txt")
    file1.parent.mkdir(parents=True, exist_ok=True)
    file1.write_text("hello")

    artifact.add_dir("baz")

    with pytest.raises(FileNotFoundError):
        artifact.remove("file1.txt")
    with pytest.raises(FileNotFoundError):
        artifact.remove("bar/")

    assert len(artifact.manifest.entries) == 1


def test_remove_manifest_entry(artifact):
    entry = artifact.add_reference(Path(__file__).as_uri())[0]

    artifact.remove(entry)

    assert artifact.manifest.entries == {}


def test_artifact_table_deserialize_timestamp_column():
    artifact_json = {
        "_type": "table",
        "column_types": {
            "params": {
                "type_map": {
                    "Date Time": {
                        "params": {
                            "allowed_types": [
                                {"wb_type": "none"},
                                {"wb_type": "timestamp"},
                            ]
                        },
                        "wb_type": "union",
                    },
                }
            },
            "wb_type": "typedDict",
        },
        "columns": [
            "Date Time",
        ],
        "data": [
            [
                1230800400000.0,
            ],
            [
                None,
            ],
        ],
    }

    artifact_json_non_null = {
        "_type": "table",
        "column_types": {
            "params": {
                "type_map": {
                    "Date Time": {"wb_type": "timestamp"},
                }
            },
            "wb_type": "typedDict",
        },
        "columns": [
            "Date Time",
        ],
        "data": [
            [
                1230800400000.0,
            ],
            [
                1230807600000.0,
            ],
        ],
    }

    for art in (artifact_json, artifact_json_non_null):
        artifact = Artifact(name="test", type="test")
        timestamp_idx = art["columns"].index("Date Time")
        table = wandb.Table.from_json(art, artifact)
        assert [row[timestamp_idx] for row in table.data] == [
            datetime.fromtimestamp(row[timestamp_idx] / 1000.0, tz=timezone.utc)
            if row[timestamp_idx] is not None
            else None
            for row in art["data"]
        ]


def test_add_obj_wbimage_no_classes(assets_path, artifact):
    im_path = str(assets_path("2x2.png"))

    wb_image = wandb.Image(
        im_path,
        masks={
            "ground_truth": {
                "path": im_path,
            },
        },
    )
    with pytest.raises(ValueError):
        artifact.add(wb_image, "my-image")


def test_add_obj_wbimage(assets_path, artifact):
    im_path = str(assets_path("2x2.png"))

    wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
    artifact.add(wb_image, "my-image")

    manifest = artifact.manifest.to_manifest_json()
    assert artifact.digest == "7772370e2243066215a845a34f3cc42c"
    assert manifest["contents"] == {
        "media/classes/65347c6442e21b09b198d62e080e46ce_cls.classes.json": {
            "digest": "eG00DqdCcCBqphilriLNfw==",
            "size": 64,
        },
        "media/images/641e917f31888a48f546/2x2.png": {
            "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
            "size": 71,
        },
        "my-image.image-file.json": {
            "digest": "IcEgVbPW7fE1a+g577K+VQ==",
            "size": 346,
        },
    }


@pytest.mark.parametrize("overwrite", [True, False])
def test_add_obj_wbimage_again_after_edit(
    tmp_path, assets_path, copy_asset, overwrite, artifact
):
    orig_path1 = assets_path("test.png")
    orig_path2 = assets_path("2x2.png")
    assert filecmp.cmp(orig_path1, orig_path2) is False  # Consistency check

    im_path = tmp_path / "image.png"

    copied_path = copy_asset(orig_path1.name, im_path)
    assert im_path == copied_path  # Consistency check
    assert filecmp.cmp(orig_path1, im_path) is True  # Consistency check

    image_name = "my-image"

    wb_image = wandb.Image(str(im_path))
    artifact.add(wb_image, image_name, overwrite=overwrite)

    manifest1 = artifact.manifest.to_manifest_json()
    digest1 = artifact.digest
    manifest_contents1 = manifest1["contents"]
    assert digest1 == "2a7a8a7f29c929fe05b57983a2944fca"
    assert len(manifest_contents1) == 2

    # Modify the object, keeping the path unchanged
    copied_path = copy_asset(orig_path2.name, im_path)
    assert im_path == copied_path  # Consistency check
    assert filecmp.cmp(orig_path2, im_path) is True  # Consistency check

    wb_image = wandb.Image(str(im_path))
    artifact.add(wb_image, image_name, overwrite=overwrite)

    manifest2 = artifact.manifest.to_manifest_json()
    digest2 = artifact.digest
    manifest_contents2 = manifest2["contents"]

    assert overwrite is (digest2 != digest1)
    assert overwrite is (manifest_contents2 != manifest_contents1)

    # Regardless, we should have the same file paths/names in the manifest
    assert manifest_contents1.keys() == manifest_contents2.keys()


def test_add_obj_using_brackets(assets_path, artifact):
    im_path = str(assets_path("2x2.png"))

    wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
    artifact["my-image"] = wb_image

    manifest = artifact.manifest.to_manifest_json()
    assert artifact.digest == "7772370e2243066215a845a34f3cc42c"
    assert manifest["contents"] == {
        "media/classes/65347c6442e21b09b198d62e080e46ce_cls.classes.json": {
            "digest": "eG00DqdCcCBqphilriLNfw==",
            "size": 64,
        },
        "media/images/641e917f31888a48f546/2x2.png": {
            "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
            "size": 71,
        },
        "my-image.image-file.json": {
            "digest": "IcEgVbPW7fE1a+g577K+VQ==",
            "size": 346,
        },
    }

    with pytest.raises(ArtifactNotLoggedError):
        _ = artifact["my-image"]


@pytest.mark.parametrize("add_duplicate", [True, False], ids=["duplicate", "unique"])
def test_duplicate_wbimage_from_file(assets_path, artifact, add_duplicate):
    im_path_1 = str(assets_path("test.png"))
    im_path_2 = str(assets_path("test2.png"))

    wb_image_1 = wandb.Image(im_path_1)
    wb_image_2 = wandb.Image(im_path_1) if add_duplicate else wandb.Image(im_path_2)

    artifact.add(wb_image_1, "my-image_1")
    artifact.add(wb_image_2, "my-image_2")

    if add_duplicate:
        assert len(artifact.manifest.entries) == 3
    else:
        assert len(artifact.manifest.entries) == 4


def test_deduplicate_wbimage_from_array():
    im_data_1 = np.random.rand(300, 300, 3)
    im_data_2 = np.random.rand(300, 300, 3)

    artifact = Artifact(type="dataset", name="artifact")
    wb_image_1 = wandb.Image(im_data_1)
    wb_image_2 = wandb.Image(im_data_2)
    artifact.add(wb_image_1, "my-image_1")
    artifact.add(wb_image_2, "my-image_2")
    assert len(artifact.manifest.entries) == 4

    artifact = Artifact(type="dataset", name="artifact")
    wb_image_1 = wandb.Image(im_data_1)
    wb_image_2 = wandb.Image(im_data_2)
    wb_image_3 = wandb.Image(im_data_1)  # yes, should be 1
    artifact.add(wb_image_1, "my-image_1")
    artifact.add(wb_image_2, "my-image_2")
    artifact.add(wb_image_3, "my-image_3")
    assert len(artifact.manifest.entries) == 5


@pytest.mark.parametrize("add_duplicate", [True, False], ids=["duplicate", "unique"])
def test_deduplicate_wbimagemask_from_array(artifact, add_duplicate):
    im_data_1 = np.random.randint(0, 10, (300, 300))
    im_data_2 = np.random.randint(0, 10, (300, 300))

    wb_imagemask_1 = data_types.ImageMask({"mask_data": im_data_1}, key="test")
    wb_imagemask_2 = data_types.ImageMask(
        {"mask_data": im_data_1 if add_duplicate else im_data_2}, key="test2"
    )

    artifact.add(wb_imagemask_1, "my-imagemask_1")
    artifact.add(wb_imagemask_2, "my-imagemask_2")

    if add_duplicate:
        assert len(artifact.manifest.entries) == 3
    else:
        assert len(artifact.manifest.entries) == 4


def test_add_obj_wbimage_classes_obj(assets_path, artifact):
    im_path = str(assets_path("2x2.png"))

    classes = wandb.Classes([{"id": 0, "name": "person"}])
    wb_image = wandb.Image(im_path, classes=classes)
    artifact.add(wb_image, "my-image")

    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"] == {
        "media/classes/65347c6442e21b09b198d62e080e46ce_cls.classes.json": {
            "digest": "eG00DqdCcCBqphilriLNfw==",
            "size": 64,
        },
        "media/images/641e917f31888a48f546/2x2.png": {
            "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
            "size": 71,
        },
        "my-image.image-file.json": {
            "digest": "IcEgVbPW7fE1a+g577K+VQ==",
            "size": 346,
        },
    }


def test_add_obj_wbimage_classes_obj_already_added(assets_path, artifact):
    im_path = str(assets_path("2x2.png"))

    classes = wandb.Classes([{"id": 0, "name": "person"}])
    artifact.add(classes, "my-classes")
    wb_image = wandb.Image(im_path, classes=classes)
    artifact.add(wb_image, "my-image")

    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"] == {
        "my-classes.classes.json": {
            "digest": "eG00DqdCcCBqphilriLNfw==",
            "size": 64,
        },
        "media/classes/65347c6442e21b09b198d62e080e46ce_cls.classes.json": {
            "digest": "eG00DqdCcCBqphilriLNfw==",
            "size": 64,
        },
        "media/images/641e917f31888a48f546/2x2.png": {
            "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
            "size": 71,
        },
        "my-image.image-file.json": {
            "digest": "IcEgVbPW7fE1a+g577K+VQ==",
            "size": 346,
        },
    }


def test_add_obj_wbimage_image_already_added(assets_path, artifact):
    im_path = str(assets_path("2x2.png"))

    artifact.add_file(im_path)
    wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
    artifact.add(wb_image, "my-image")

    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"] == {
        "2x2.png": {"digest": "L1pBeGPxG+6XVRQk4WuvdQ==", "size": 71},
        "media/classes/65347c6442e21b09b198d62e080e46ce_cls.classes.json": {
            "digest": "eG00DqdCcCBqphilriLNfw==",
            "size": 64,
        },
        "my-image.image-file.json": {
            "digest": "BPGPVjCBRxX6MNySpv2Rmg==",
            "size": 312,
        },
    }


def test_add_obj_wbtable_images(assets_path, artifact):
    im_path = str(assets_path("2x2.png"))

    wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
    wb_table = wandb.Table(["examples"])
    wb_table.add_data(wb_image)
    wb_table.add_data(wb_image)
    artifact.add(wb_table, "my-table")

    manifest = artifact.manifest.to_manifest_json()

    assert manifest["contents"] == {
        "media/classes/65347c6442e21b09b198d62e080e46ce_cls.classes.json": {
            "digest": "eG00DqdCcCBqphilriLNfw==",
            "size": 64,
        },
        "media/images/641e917f31888a48f546/2x2.png": {
            "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
            "size": 71,
        },
        "my-table.table.json": {"digest": "UN1SfxHpRdt/OOy7TrjvdQ==", "size": 1315},
    }


def test_add_obj_wbtable_images_duplicate_name(assets_path, artifact):
    img_1 = str(assets_path("2x2.png"))
    img_2 = str(assets_path("test2.png"))

    os.mkdir("dir1")
    shutil.copy(img_1, "dir1/img.png")
    os.mkdir("dir2")
    shutil.copy(img_2, "dir2/img.png")

    wb_image_1 = wandb.Image(os.path.join("dir1", "img.png"))
    wb_image_2 = wandb.Image(os.path.join("dir2", "img.png"))
    wb_table = wandb.Table(["examples"])
    wb_table.add_data(wb_image_1)
    wb_table.add_data(wb_image_2)
    artifact.add(wb_table, "my-table")

    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"] == {
        "media/images/641e917f31888a48f546/img.png": {
            "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
            "size": 71,
        },
        "media/images/cf37c38fd1dca3aaba6e/img.png": {
            "digest": "pQVvBBgcuG+jTN0Xo97eZQ==",
            "size": 8837,
        },
        "my-table.table.json": {"digest": "rkNgqyX3yGEQ1UxM7hsGjQ==", "size": 1006},
    }


def test_add_partition_folder(artifact):
    table_name = "dataset"
    table_parts_dir = "dataset_parts"

    partition_table = wandb.data_types.PartitionedTable(parts_path=table_parts_dir)
    artifact.add(partition_table, table_name)
    manifest = artifact.manifest.to_manifest_json()
    assert artifact.digest == "c6a4d80ed84fd68df380425ded894b19"
    assert manifest["contents"]["dataset.partitioned-table.json"] == {
        "digest": "uo/SjoAO+O7pcSfg+yhlDg==",
        "size": 61,
    }


@pytest.mark.parametrize(
    "headers,expected_digest",
    [
        ({"ETag": "my-etag"}, "my-etag"),
        # TODO(spencerpearson): I think this test is wrong:
        # if no etag is provided, shouldn't we hash the response body, not simply use the URL?
        (None, "https://example.com/foo.json?bar=abc"),
    ],
)
def test_http_storage_handler_uses_etag_for_digest(
    headers: Optional[Mapping[str, str]],
    expected_digest: Optional[str],
    artifact,
):
    with responses.RequestsMock() as rsps, requests.Session() as session:
        rsps.add(
            "GET",
            "https://example.com/foo.json?bar=abc",
            json={"result": 1},
            headers=headers,
        )
        handler = HTTPHandler(session)

        [entry] = handler.store_path(
            artifact, "https://example.com/foo.json?bar=abc", "foo.json"
        )
        assert entry.path == "foo.json"
        assert entry.ref == "https://example.com/foo.json?bar=abc"
        assert entry.digest == expected_digest


def test_s3_storage_handler_load_path_missing_reference(monkeypatch, user, artifact):
    # Create an artifact that references a non-existent S3 object.
    mock_boto(artifact, version_id="")
    artifact.add_reference("s3://my-bucket/my_object.pb")

    with wandb.init(project="test") as run:
        run.log_artifact(artifact)
    artifact.wait()

    # Patch the S3 handler to return a 404 error when checking the ETag.
    def bad_request(*args, **kwargs):
        raise util.get_module("botocore").exceptions.ClientError(
            operation_name="HeadObject",
            error_response={"Error": {"Code": "404", "Message": "Not Found"}},
        )

    monkeypatch.setattr(S3Handler, "_etag_from_obj", bad_request)

    with wandb.init(project="test") as run:
        with pytest.raises(FileNotFoundError, match="Unable to find"):
            artifact.download()


def test_change_artifact_collection_type(user):
    with wandb.init() as run:
        artifact = Artifact("image_data", "data")
        run.log_artifact(artifact)

    with wandb.init() as run:
        artifact = run.use_artifact("image_data:latest")
        artifact.collection.change_type("lucas_type")

    with wandb.init() as run:
        artifact = run.use_artifact("image_data:latest")
        assert artifact.type == "lucas_type"


def test_change_artifact_collection_type_to_internal_type(user):
    with wandb.init() as run:
        artifact = Artifact("image_data", "data")
        run.log_artifact(artifact).wait()

    internal_type = f"{RESERVED_ARTIFACT_TYPE_PREFIX}invalid"
    collection = artifact.collection
    with wandb.init() as run:
        # test deprecated change_type errors for changing to internal type
        with pytest.raises(CommError, match="is reserved for internal use"):
            collection.change_type(internal_type)

        # test .save()
        with pytest.raises(CommError, match="is reserved for internal use"):
            collection.type = internal_type
            collection.save()


def test_change_type_of_internal_artifact_collection(user):
    internal_type = f"{RESERVED_ARTIFACT_TYPE_PREFIX}invalid"
    with wandb.init() as run:
        artifact = InternalArtifact("test-internal", internal_type)
        run.log_artifact(artifact).wait()

    collection = artifact.collection
    with wandb.init() as run:
        # test deprecated change_type
        with pytest.raises(
            CommError, match="is an internal type and cannot be changed"
        ):
            collection.change_type("model")

        # test .save()
        with pytest.raises(
            CommError, match="is an internal type and cannot be changed"
        ):
            collection.type = "model"
            collection.save()


@pytest.mark.parametrize(
    "invalid_name",
    [
        "a" * (ARTIFACT_NAME_MAXLEN + 1),  # Name too long
        "my/artifact",  # Invalid character(s)
    ],
)
def test_setting_invalid_artifact_collection_name(user, api, invalid_name):
    """Setting an invalid name on an existing ArtifactCollection should fail and raise an error."""
    orig_name = "valid-name"

    with wandb.init() as run:
        artifact = Artifact(orig_name, "data")
        run.log_artifact(artifact)

    collection = api.artifact_collection(type_name="data", name=orig_name)

    with pytest.raises(ValueError):
        collection.name = invalid_name

    assert collection.name == orig_name


def test_save_artifact_sequence(monkeypatch, user, api):
    with wandb.init() as run:
        artifact = Artifact("sequence_name", "data")
        run.log_artifact(artifact)
        artifact.wait()

        artifact = run.use_artifact("sequence_name:latest")
        collection = api.artifact_collection("data", "sequence_name")
        collection.description = "new description"
        collection.name = "new_name"
        collection.type = "new_type"
        collection.tags = ["tag"]
        collection.save()

        artifact = run.use_artifact("new_name:latest")
        assert artifact.type == "new_type"
        collection = artifact.collection
        assert collection.type == "new_type"
        assert collection.name == "new_name"
        assert collection.description == "new description"
        assert len(collection.tags) == 1 and collection.tags[0] == "tag"

        collection.tags = ["new_tag"]
        collection.save()

        artifact = run.use_artifact("new_name:latest")
        collection = artifact.collection
        assert len(collection.tags) == 1 and collection.tags[0] == "new_tag"


def test_artifact_standard_url(user, api):
    with wandb.init() as run:
        artifact = Artifact("sequence_name", "data")
        run.log_artifact(artifact)
        artifact.wait()

        artifact = run.use_artifact("sequence_name:latest")
        expected_url = f"{util.app_url(run.settings.base_url)}/{run.entity}/{run.project}/artifacts/data/sequence_name/{artifact.version}"

        assert artifact.url == expected_url


def test_artifact_model_registry_url(user, api):
    with wandb.init() as run:
        artifact = wandb.Artifact("sequence_name", "model")
        run.log_artifact(artifact)
        artifact.wait()
        run.link_artifact(artifact=artifact, target_path="test_model_portfolio")
        linked_model_art = run.use_artifact(
            f"{artifact.entity}/{artifact.project}/test_model_portfolio:latest"
        )

        base_url = util.app_url(run.settings.base_url)

        encoded_path = f"{linked_model_art.entity}/{linked_model_art.project}/{linked_model_art.collection.name}"
        selection_path = quote(encoded_path, safe="")

        expected_url = (
            f"{base_url}/{linked_model_art.entity}/registry/model?"
            f"selectionPath={selection_path}&view=membership&version={linked_model_art.version}"
        )

        assert linked_model_art.url == expected_url


def test_save_artifact_portfolio(user, api):
    with wandb.init() as run:
        artifact = Artifact("image_data", "data")
        run.log_artifact(artifact)
        artifact.link("portfolio_name")
        artifact.wait()

        portfolio = api.artifact_collection("data", "portfolio_name")
        portfolio.description = "new description"
        portfolio.name = "new_name"
        with pytest.raises(ValueError):
            portfolio.type = "new_type"
        portfolio.tags = ["tag"]
        portfolio.save()

        port_artifact = run.use_artifact("new_name:v0")
        portfolio = port_artifact.collection
        assert portfolio.name == "new_name"
        assert portfolio.description == "new description"
        assert len(portfolio.tags) == 1 and portfolio.tags[0] == "tag"

        portfolio.tags = ["new_tag"]
        portfolio.save()

        artifact = run.use_artifact("new_name:latest")
        portfolio = artifact.collection
        assert len(portfolio.tags) == 1 and portfolio.tags[0] == "new_tag"


def test_s3_storage_handler_load_path_missing_reference_allowed(
    monkeypatch, user, capsys, artifact
):
    # Create an artifact that references a non-existent S3 object.
    mock_boto(artifact, version_id="")
    artifact.add_reference("s3://my-bucket/my_object.pb")

    with wandb.init(project="test") as run:
        run.log_artifact(artifact)
    artifact.wait()

    # Patch the S3 handler to return a 404 error when checking the ETag.
    def bad_request(*args, **kwargs):
        raise util.get_module("botocore").exceptions.ClientError(
            operation_name="HeadObject",
            error_response={"Error": {"Code": "404", "Message": "Not Found"}},
        )

    monkeypatch.setattr(S3Handler, "_etag_from_obj", bad_request)

    with wandb.init(project="test") as run:
        artifact.download(allow_missing_references=True)

    # It should still log a warning about skipping the missing reference.
    assert "Unable to find my_object.pb" in capsys.readouterr().err


def test_s3_storage_handler_load_path_uses_cache(tmp_path):
    uri = "s3://some-bucket/path/to/file.json"
    etag = "some etag"

    cache = artifact_file_cache.ArtifactFileCache(tmp_path)
    path, _, opener = cache.check_etag_obj_path(uri, etag, 123)
    with opener() as f:
        f.write(123 * "a")

    handler = S3Handler()
    handler._cache = cache

    local_path = handler.load_path(
        ArtifactManifestEntry(
            path="foo/bar",
            ref=uri,
            digest=etag,
            size=123,
        ),
        local=True,
    )
    assert local_path == path


def test_tracking_storage_handler(artifact):
    handler = TrackingHandler()
    [entry] = handler.store_path(artifact, path="/path/to/file.txt", name="some-file")
    assert entry.path == "some-file"
    assert entry.ref == "/path/to/file.txt"
    assert entry.digest == entry.ref

    # TODO(spencerpearson): THIS TEST IS BROKEN. I'm pretty sure.
    # I'm commenting it out rather than fixing it because this commit should be a no-op.
    #
    # Empirically, this test fails with:
    #   AssertionError: assert 'some-file' == '/path/to/file.txt'
    # But 'some-file' started out as a `name`, i.e. a LogicalPath,
    # representing the location of the file *within the artifact*
    # rather than *on the filesystem*.
    #
    # assert handler.load_path(entry) == "/path/to/file.txt"


def test_manifest_json_version():
    pd_manifest = wandb.proto.wandb_internal_pb2.ArtifactManifest()
    pd_manifest.version = 1
    manifest = wandb.sdk.internal.sender._manifest_json_from_proto(pd_manifest)
    assert manifest["version"] == 1


@pytest.mark.parametrize("version", ["1", 1.0])
def test_manifest_version_is_integer(version):
    pd_manifest = wandb.proto.wandb_internal_pb2.ArtifactManifest()
    with pytest.raises(TypeError):
        pd_manifest.version = version


@pytest.mark.parametrize("version", [0, 2])
def test_manifest_json_invalid_version(version):
    pd_manifest = wandb.proto.wandb_internal_pb2.ArtifactManifest()
    pd_manifest.version = version
    with pytest.raises(Exception) as e:
        wandb.sdk.internal.sender._manifest_json_from_proto(pd_manifest)
    assert "manifest version" in str(e.value)


@pytest.mark.flaky
@pytest.mark.xfail(reason="flaky")
def test_cache_cleanup_allows_upload(user, tmp_path, monkeypatch, artifact):
    monkeypatch.setenv("WANDB_CACHE_DIR", str(tmp_path))
    cache = artifact_file_cache.get_artifact_file_cache()

    with open("test-file", "wb") as f:
        f.truncate(2**20)
        f.flush()
        os.fsync(f)
    artifact.add_file("test-file")

    # We haven't cached it and can't reclaim its bytes.
    assert cache.cleanup(0) == 0
    # Deleting the file also shouldn't interfere with the upload.
    os.remove("test-file")

    # We're still able to upload the artifact.
    with wandb.init() as run:
        run.log_artifact(artifact)
        artifact.wait()

    manifest_entry = artifact.manifest.entries["test-file"]
    _, found, _ = cache.check_md5_obj_path(manifest_entry.digest, 2**20)

    # Now the file should be in the cache.
    # Even though this works in production, the test often fails. I don't know why :(.
    assert found
    assert cache.cleanup(0) == 2**20


def test_artifact_ttl_setter_getter():
    art = Artifact("test", type="test")
    with pytest.raises(ArtifactNotLoggedError):
        _ = art.ttl
    assert art._ttl_duration_seconds is None
    assert art._ttl_changed is False
    assert art._ttl_is_inherited

    art = Artifact("test", type="test")
    art.ttl = None
    assert art.ttl is None
    assert art._ttl_duration_seconds is None
    assert art._ttl_changed
    assert art._ttl_is_inherited is False

    art = Artifact("test", type="test")
    art.ttl = ArtifactTTL.INHERIT
    with pytest.raises(ArtifactNotLoggedError):
        _ = art.ttl
    assert art._ttl_duration_seconds is None
    assert art._ttl_changed
    assert art._ttl_is_inherited

    ttl_timedelta = timedelta(days=100)
    art = Artifact("test", type="test")
    art.ttl = ttl_timedelta
    assert art.ttl == ttl_timedelta
    assert art._ttl_duration_seconds == int(ttl_timedelta.total_seconds())
    assert art._ttl_changed
    assert art._ttl_is_inherited is False

    art = Artifact("test", type="test")
    with pytest.raises(ValueError):
        art.ttl = timedelta(days=-1)
