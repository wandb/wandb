from __future__ import annotations

import unittest.mock

from pytest import fixture, mark
from wandb import Artifact


@fixture
def mock_azure_handler():  # noqa: C901
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

    class BlobProperties:
        def __init__(self, name, version_id, etag, size, metadata):
            self.name = name
            self.version_id = version_id
            self.etag = etag
            self.size = size
            self.metadata = metadata

        def has_key(self, k):
            return k in self.__dict__

    blobs = [
        BlobProperties(
            "my-blob",
            version_id=None,
            etag="my-blob version None",
            size=42,
            metadata={},
        ),
        BlobProperties(
            "my-blob", version_id="v2", etag="my-blob version v2", size=42, metadata={}
        ),
        BlobProperties(
            "my-dir/a",
            version_id=None,
            etag="my-dir/a version None",
            size=42,
            metadata={},
        ),
        BlobProperties(
            "my-dir/b",
            version_id=None,
            etag="my-dir/b version None",
            size=42,
            metadata={},
        ),
        BlobProperties(
            "my-dir",
            version_id=None,
            etag="my-dir version None",
            size=0,
            metadata={"hdi_isfolder": "true"},
        ),
    ]

    class AzureStorageBlobModule:
        def __init__(self):
            self.BlobServiceClient = BlobServiceClient

    class AzureIdentityModule:
        def __init__(self):
            self.DefaultAzureCredential = lambda: None

    def _get_module(self, name):
        if name == "azure.storage.blob":
            return AzureStorageBlobModule()
        if name == "azure.identity":
            return AzureIdentityModule()
        raise NotImplementedError

    with unittest.mock.patch(
        "wandb.sdk.artifacts.storage_handlers.azure_handler.AzureHandler._get_module",
        new=_get_module,
    ):
        yield


@fixture
def my_artifact() -> Artifact:
    """A test artifact with a custom type."""
    return Artifact("my_artifact", type="my_type")


@mark.parametrize("name", [None, "my-name"])
@mark.parametrize("version_id", [None, "v2"])
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


@mark.parametrize("name", [None, "my-name"])
@mark.parametrize("version_id", [None, "v2"])
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
    artifact = Artifact("my_artifact", type="my_type")
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
