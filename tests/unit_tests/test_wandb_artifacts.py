import base64
import hashlib
import os
import shutil
from datetime import datetime, timezone

import numpy as np
import pytest
import wandb
import wandb.data_types as data_types
from wandb import util


def mock_boto(artifact, path=False, content_type=None):
    class S3Object:
        def __init__(self, name="my_object.pb", metadata=None, version_id=None):
            self.metadata = metadata or {"md5": "1234567890abcde"}
            self.e_tag = '"1234567890abcde"'
            self.version_id = version_id or "1"
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

    class Filtered:
        def limit(self, *args, **kwargs):
            return [S3Object(), S3Object(name="my_other_object.pb")]

    class S3Objects:
        def filter(self, **kwargs):
            return Filtered()

    class S3Bucket:
        def __init__(self, *args, **kwargs):
            self.objects = S3Objects()

    class S3Resource:
        def Object(self, bucket, key):  # noqa: N802
            return S3Object()

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
    handler = artifact._storage_policy._handler._handlers["s3"]
    handler._s3 = mock
    handler._botocore = util.get_module("botocore")
    handler._botocore.exceptions = util.get_module("botocore.exceptions")
    return mock


def mock_gcs(artifact, path=False):
    class Blob:
        def __init__(self, name="my_object.pb", metadata=None, generation=None):
            self.md5_hash = "1234567890abcde"
            self.etag = "1234567890abcde"
            self.generation = generation or "1"
            self.name = name
            self.size = 10

    class GSBucket:
        def __init__(self):
            self.versioning_enabled = True

        def reload(self, *args, **kwargs):
            return

        def get_blob(self, *args, **kwargs):
            return None if path else Blob(generation=kwargs.get("generation"))

        def list_blobs(self, *args, **kwargs):
            return [Blob(), Blob(name="my_other_object.pb")]

    class GSClient:
        def bucket(self, bucket):
            return GSBucket()

    mock = GSClient()
    handler = artifact._storage_policy._handler._handlers["gs"]
    handler._client = mock
    return mock


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
    handler = artifact._storage_policy._handler._handlers["http"]
    handler._session = mock
    return mock


def md5_string(string):
    hash_md5 = hashlib.md5()
    hash_md5.update(string.encode())
    return base64.b64encode(hash_md5.digest()).decode("ascii")


def test_add_one_file():
    with open("file1.txt", "w") as f:
        f.write("hello")
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    artifact.add_file("file1.txt")

    assert artifact.digest == "a00c2239f036fb656c1dcbf9a32d89b4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "size": 5,
    }


def test_add_named_file():
    with open("file1.txt", "w") as f:
        f.write("hello")
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    artifact.add_file("file1.txt", name="great-file.txt")

    assert artifact.digest == "585b9ada17797e37c9cbab391e69b8c5"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["great-file.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "size": 5,
    }


def test_add_new_file():
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    with artifact.new_file("file1.txt") as f:
        f.write("hello")

    assert artifact.digest == "a00c2239f036fb656c1dcbf9a32d89b4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "size": 5,
    }


def test_add_new_file_encode_error(capsys):
    with pytest.raises(UnicodeEncodeError):
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        with artifact.new_file("wave.txt", mode="w", encoding="ascii") as f:
            f.write("∂²u/∂t²=c²·∂²u/∂x²")
    assert "ERROR Failed to open the provided file" in capsys.readouterr().err


def test_add_dir():
    with open("file1.txt", "w") as f:
        f.write("hello")

    artifact = wandb.Artifact(type="dataset", name="my-arty")
    artifact.add_dir(".")

    # note: we are auto-using local_netrc resulting in
    # the .netrc file being picked by the artifact, see manifest

    assert artifact.digest == "c409156beb903b74fe9097bb249a26d2"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "size": 5,
    }


def test_add_named_dir():
    with open("file1.txt", "w") as f:
        f.write("hello")
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    artifact.add_dir(".", name="subdir")

    assert artifact.digest == "a2184d2d318ddb2f3aa82818365827df"

    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["subdir/file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "size": 5,
    }


def test_add_reference_local_file():
    with open("file1.txt", "w") as f:
        f.write("hello")

    artifact = wandb.Artifact(type="dataset", name="my-arty")
    e = artifact.add_reference("file://file1.txt")[0]
    assert e.ref_target() == "file://file1.txt"

    assert artifact.digest == "a00c2239f036fb656c1dcbf9a32d89b4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "ref": "file://file1.txt",
        "size": 5,
    }


def test_add_reference_local_file_no_checksum():

    with open("file1.txt", "w") as f:
        f.write("hello")
    size = os.path.getsize("file1.txt")
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    artifact.add_reference("file://file1.txt", checksum=False)

    assert artifact.digest == "415f3bca4b095cbbbbc47e0d44079e05"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": md5_string(str(size)),
        "ref": "file://file1.txt",
        "size": size,
    }


def test_add_reference_local_dir():

    with open("file1.txt", "w") as f:
        f.write("hello")
    os.mkdir("nest")
    with open("nest/file2.txt", "w") as f:
        f.write("my")
    os.mkdir("nest/nest")
    with open("nest/nest/file3.txt", "w") as f:
        f.write("dude")

    artifact = wandb.Artifact(type="dataset", name="my-arty")
    artifact.add_reference("file://" + os.getcwd())

    assert artifact.digest == "13d688af2d0dab74e0544a4c5c542735"
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


def test_add_reference_local_dir_no_checksum():

    path_1 = os.path.join("file1.txt")
    with open(path_1, "w") as f:
        f.write("hello")
    size_1 = os.path.getsize(path_1)

    path_2 = os.path.join("nest", "file2.txt")
    os.mkdir("nest")
    with open(path_2, "w") as f:
        f.write("my")
    size_2 = os.path.getsize(path_2)

    path_3 = os.path.join("nest", "nest", "file3.txt")
    os.mkdir("nest/nest")
    with open(path_3, "w") as f:
        f.write("dude")
    size_3 = os.path.getsize(path_3)

    artifact = wandb.Artifact(type="dataset", name="my-arty")
    artifact.add_reference("file://" + os.getcwd(), checksum=False)

    assert artifact.digest == "7ca355c7f600119151d607c98921ab50"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": md5_string(str(size_1)),
        "ref": "file://" + os.path.join(os.getcwd(), "file1.txt"),
        "size": size_1,
    }
    assert manifest["contents"]["nest/file2.txt"] == {
        "digest": md5_string(str(size_2)),
        "ref": "file://" + os.path.join(os.getcwd(), "nest", "file2.txt"),
        "size": size_2,
    }
    assert manifest["contents"]["nest/nest/file3.txt"] == {
        "digest": md5_string(str(size_3)),
        "ref": "file://" + os.path.join(os.getcwd(), "nest", "nest", "file3.txt"),
        "size": size_3,
    }


def test_add_reference_local_dir_with_name():

    with open("file1.txt", "w") as f:
        f.write("hello")
    os.mkdir("nest")
    with open("nest/file2.txt", "w") as f:
        f.write("my")
    os.mkdir("nest/nest")
    with open("nest/nest/file3.txt", "w") as f:
        f.write("dude")

    artifact = wandb.Artifact(type="dataset", name="my-arty")
    artifact.add_reference("file://" + os.getcwd(), name="top")

    assert artifact.digest == "c406b09e8b6cb180e9be7fa010bf5a83"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["top/file1.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "ref": "file://" + os.path.join(os.getcwd(), "top", "file1.txt"),
        "size": 5,
    }
    assert manifest["contents"]["top/nest/file2.txt"] == {
        "digest": "aGTzidmHZDa8h3j/Bx0bbA==",
        "ref": "file://" + os.path.join(os.getcwd(), "top", "nest", "file2.txt"),
        "size": 2,
    }
    assert manifest["contents"]["top/nest/nest/file3.txt"] == {
        "digest": "E7c+2uhEOZC+GqjxpIO8Jw==",
        "ref": "file://"
        + os.path.join(os.getcwd(), "top", "nest", "nest", "file3.txt"),
        "size": 4,
    }


def test_add_s3_reference_object():

    artifact = wandb.Artifact(type="dataset", name="my-arty")
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


def test_add_s3_reference_object_with_version():

    artifact = wandb.Artifact(type="dataset", name="my-arty")
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


def test_add_s3_reference_object_with_name():

    artifact = wandb.Artifact(type="dataset", name="my-arty")
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


def test_add_s3_reference_path(runner, capsys):
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
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


def test_add_s3_reference_path_with_content_type(runner, capsys):
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        mock_boto(artifact, path=False, content_type="application/x-directory")
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


def test_add_s3_max_objects():

    artifact = wandb.Artifact(type="dataset", name="my-arty")
    mock_boto(artifact, path=True)
    with pytest.raises(ValueError):
        artifact.add_reference("s3://my-bucket/", max_objects=1)


def test_add_reference_s3_no_checksum():

    with open("file1.txt", "w") as f:
        f.write("hello")
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    mock_boto(artifact)
    # TODO: Should we require name in this case?
    artifact.add_reference("s3://my_bucket/file1.txt", checksum=False)

    assert artifact.digest == "52631787ed3579325f985dc0f2374040"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["file1.txt"] == {
        "digest": "s3://my_bucket/file1.txt",
        "ref": "s3://my_bucket/file1.txt",
    }


def test_add_gs_reference_object():

    artifact = wandb.Artifact(type="dataset", name="my-arty")
    mock_gcs(artifact)
    artifact.add_reference("gs://my-bucket/my_object.pb")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["my_object.pb"] == {
        "digest": "1234567890abcde",
        "ref": "gs://my-bucket/my_object.pb",
        "extra": {"etag": "1234567890abcde", "versionID": "1"},
        "size": 10,
    }


def test_add_gs_reference_object_with_version():

    artifact = wandb.Artifact(type="dataset", name="my-arty")
    mock_gcs(artifact)
    artifact.add_reference("gs://my-bucket/my_object.pb#2")

    assert artifact.digest == "8aec0d6978da8c2b0bf5662b3fd043a4"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["my_object.pb"] == {
        "digest": "1234567890abcde",
        "ref": "gs://my-bucket/my_object.pb",
        "extra": {"etag": "1234567890abcde", "versionID": "2"},
        "size": 10,
    }


def test_add_gs_reference_object_with_name():

    artifact = wandb.Artifact(type="dataset", name="my-arty")
    mock_gcs(artifact)
    artifact.add_reference("gs://my-bucket/my_object.pb", name="renamed.pb")

    assert artifact.digest == "bd85fe009dc9e408a5ed9b55c95f47b2"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["renamed.pb"] == {
        "digest": "1234567890abcde",
        "ref": "gs://my-bucket/my_object.pb",
        "extra": {"etag": "1234567890abcde", "versionID": "1"},
        "size": 10,
    }


def test_add_gs_reference_path(runner, capsys):
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        mock_gcs(artifact, path=True)
        artifact.add_reference("gs://my-bucket/")

        assert artifact.digest == "17955d00a20e1074c3bc96c74b724bfe"
        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"]["my_object.pb"] == {
            "digest": "1234567890abcde",
            "ref": "gs://my-bucket/my_object.pb",
            "extra": {"etag": "1234567890abcde", "versionID": "1"},
            "size": 10,
        }
        _, err = capsys.readouterr()
        assert "Generating checksum" in err


def test_add_http_reference_path():

    artifact = wandb.Artifact(type="dataset", name="my-arty")
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


def test_add_reference_named_local_file():

    with open("file1.txt", "w") as f:
        f.write("hello")
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    artifact.add_reference("file://file1.txt", name="great-file.txt")

    assert artifact.digest == "585b9ada17797e37c9cbab391e69b8c5"
    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["great-file.txt"] == {
        "digest": "XUFAKrxLKna5cZ2REBfFkg==",
        "ref": "file://file1.txt",
        "size": 5,
    }


def test_add_reference_unknown_handler():

    artifact = wandb.Artifact(type="dataset", name="my-arty")
    artifact.add_reference("ref://example.com/somefile.txt", name="ref")

    assert artifact.digest == "410ade94865e89ebe1f593f4379ac228"

    manifest = artifact.manifest.to_manifest_json()
    assert manifest["contents"]["ref"] == {
        "digest": "ref://example.com/somefile.txt",
        "ref": "ref://example.com/somefile.txt",
    }


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
        artifact = wandb.Artifact(name="test", type="test")
        timestamp_idx = art["columns"].index("Date Time")
        table = wandb.Table.from_json(art, artifact)
        assert [row[timestamp_idx] for row in table.data] == [
            datetime.fromtimestamp(row[timestamp_idx] / 1000.0, tz=timezone.utc)
            if row[timestamp_idx] is not None
            else None
            for row in art["data"]
        ]


def test_add_obj_wbimage_no_classes(assets_path):
    im_path = str(assets_path("2x2.png"))

    artifact = wandb.Artifact(type="dataset", name="my-arty")
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


def test_add_obj_wbimage(assets_path):
    im_path = str(assets_path("2x2.png"))

    artifact = wandb.Artifact(type="dataset", name="my-arty")
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


def test_add_obj_using_brackets(assets_path):
    im_path = str(assets_path("2x2.png"))

    artifact = wandb.Artifact(type="dataset", name="my-arty")
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

    with pytest.raises(ValueError):
        _ = artifact["my-image"]


def test_artifact_interface_link():
    art = wandb.wandb_sdk.interface.artifacts.Artifact()
    with pytest.raises(NotImplementedError):
        _ = art.link("boom")


def test_artifact_interface_get_item():
    art = wandb.wandb_sdk.interface.artifacts.Artifact()
    with pytest.raises(NotImplementedError):
        _ = art["my-image"]


def test_artifact_interface_set_item():
    art = wandb.wandb_sdk.interface.artifacts.Artifact()
    with pytest.raises(NotImplementedError):
        art["my-image"] = 1


def test_duplicate_wbimage_from_file(assets_path):
    im_path_1 = str(assets_path("test.png"))
    im_path_2 = str(assets_path("test2.png"))

    artifact = wandb.Artifact(type="dataset", name="artifact")
    wb_image_1 = wandb.Image(im_path_1)
    wb_image_2 = wandb.Image(im_path_2)
    artifact.add(wb_image_1, "my-image_1")
    artifact.add(wb_image_2, "my-image_2")
    assert len(artifact.manifest.entries) == 4

    artifact = wandb.Artifact(type="dataset", name="artifact")
    wb_image_1 = wandb.Image(im_path_1)
    wb_image_2 = wandb.Image(im_path_1)
    artifact.add(wb_image_1, "my-image_1")
    artifact.add(wb_image_2, "my-image_2")
    assert len(artifact.manifest.entries) == 3


def test_deduplicate_wbimage_from_array():
    im_data_1 = np.random.rand(300, 300, 3)
    im_data_2 = np.random.rand(300, 300, 3)

    artifact = wandb.Artifact(type="dataset", name="artifact")
    wb_image_1 = wandb.Image(im_data_1)
    wb_image_2 = wandb.Image(im_data_2)
    artifact.add(wb_image_1, "my-image_1")
    artifact.add(wb_image_2, "my-image_2")
    assert len(artifact.manifest.entries) == 4

    artifact = wandb.Artifact(type="dataset", name="artifact")
    wb_image_1 = wandb.Image(im_data_1)
    wb_image_2 = wandb.Image(im_data_2)
    wb_image_3 = wandb.Image(im_data_1)  # yes, should be 1
    artifact.add(wb_image_1, "my-image_1")
    artifact.add(wb_image_2, "my-image_2")
    artifact.add(wb_image_3, "my-image_3")
    assert len(artifact.manifest.entries) == 5


def test_deduplicate_wbimagemask_from_array():
    im_data_1 = np.random.randint(0, 10, (300, 300))
    im_data_2 = np.random.randint(0, 10, (300, 300))

    artifact = wandb.Artifact(type="dataset", name="artifact")
    wb_imagemask_1 = data_types.ImageMask({"mask_data": im_data_1}, key="test")
    wb_imagemask_2 = data_types.ImageMask({"mask_data": im_data_2}, key="test2")
    artifact.add(wb_imagemask_1, "my-imagemask_1")
    artifact.add(wb_imagemask_2, "my-imagemask_2")
    assert len(artifact.manifest.entries) == 4

    artifact = wandb.Artifact(type="dataset", name="artifact")
    wb_imagemask_1 = data_types.ImageMask({"mask_data": im_data_1}, key="test")
    wb_imagemask_2 = data_types.ImageMask({"mask_data": im_data_1}, key="test2")
    artifact.add(wb_imagemask_1, "my-imagemask_1")
    artifact.add(wb_imagemask_2, "my-imagemask_2")
    assert len(artifact.manifest.entries) == 3


def test_add_obj_wbimage_classes_obj(assets_path):
    im_path = str(assets_path("2x2.png"))

    artifact = wandb.Artifact(type="dataset", name="my-arty")
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


def test_add_obj_wbimage_classes_obj_already_added(assets_path):
    im_path = str(assets_path("2x2.png"))

    artifact = wandb.Artifact(type="dataset", name="my-arty")
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


def test_add_obj_wbimage_image_already_added(assets_path):
    im_path = str(assets_path("2x2.png"))

    artifact = wandb.Artifact(type="dataset", name="my-arty")
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


def test_add_obj_wbtable_images(assets_path):
    im_path = str(assets_path("2x2.png"))

    artifact = wandb.Artifact(type="dataset", name="my-arty")
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
        "my-table.table.json": {"digest": "apPaCuFMSlFoP7rztfZq5Q==", "size": 1290},
    }


def test_add_obj_wbtable_images_duplicate_name(assets_path):
    img_1 = str(assets_path("2x2.png"))
    img_2 = str(assets_path("test2.png"))

    os.mkdir("dir1")
    shutil.copy(img_1, "dir1/img.png")
    os.mkdir("dir2")
    shutil.copy(img_2, "dir2/img.png")

    artifact = wandb.Artifact(type="dataset", name="my-arty")
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
        "my-table.table.json": {"digest": "hjWyKjD8J/wFtikBxnFOeA==", "size": 981},
    }


def test_add_partition_folder():

    table_name = "dataset"
    table_parts_dir = "dataset_parts"
    artifact_name = "simple_dataset"
    artifact_type = "dataset"

    artifact = wandb.Artifact(artifact_name, type=artifact_type)
    partition_table = wandb.data_types.PartitionedTable(parts_path=table_parts_dir)
    artifact.add(partition_table, table_name)
    manifest = artifact.manifest.to_manifest_json()
    print(manifest)
    print(artifact.digest)
    assert artifact.digest == "c6a4d80ed84fd68df380425ded894b19"
    assert manifest["contents"]["dataset.partitioned-table.json"] == {
        "digest": "uo/SjoAO+O7pcSfg+yhlDg==",
        "size": 61,
    }


def test_interface_commit_hash():
    artifact = wandb.wandb_sdk.interface.artifacts.Artifact()
    with pytest.raises(NotImplementedError):
        artifact.commit_hash()
