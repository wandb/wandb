import base64
import hashlib
import os
import sys
import pytest
from wandb import util
import wandb
import shutil
import wandb.data_types as data_types
import numpy as np
import pandas as pd
import time
from wandb.proto import wandb_internal_pb2 as pb

sm = wandb.wandb_sdk.internal.sender.SendManager


def mock_boto(artifact, path=False):
    class S3Object(object):
        def __init__(self, name="my_object.pb", metadata=None):
            self.metadata = metadata or {"md5": "1234567890abcde"}
            self.e_tag = '"1234567890abcde"'
            self.version_id = "1"
            self.name = name
            self.key = name
            self.content_length = 10

        def load(self):
            if path:
                raise util.get_module("botocore").exceptions.ClientError(
                    {"Error": {"Code": "404"}}, "HeadObject"
                )

    class Filtered(object):
        def limit(self, *args, **kwargs):
            return [S3Object(), S3Object(name="my_other_object.pb")]

    class S3Objects(object):
        def filter(self, **kwargs):
            return Filtered()

    class S3Bucket(object):
        def __init__(self, *args, **kwargs):
            self.objects = S3Objects()

    class S3Resource(object):
        def Object(self, bucket, key):
            return S3Object()

        def Bucket(self, bucket):
            return S3Bucket()

    mock = S3Resource()
    handler = artifact._storage_policy._handler._handlers["s3"]
    handler._s3 = mock
    handler._botocore = util.get_module("botocore")
    handler._botocore.exceptions = util.get_module("botocore.exceptions")
    return mock


def mock_gcs(artifact, path=False):
    class Blob(object):
        def __init__(self, name="my_object.pb", metadata=None):
            self.md5_hash = "1234567890abcde"
            self.etag = "1234567890abcde"
            self.generation = "1"
            self.name = name
            self.size = 10

    class GSBucket(object):
        def get_blob(self, *args, **kwargs):
            return None if path else Blob()

        def list_blobs(self, *args, **kwargs):
            return [Blob(), Blob(name="my_other_object.pb")]

    class GSClient(object):
        def bucket(self, bucket):
            return GSBucket()

    mock = GSClient()
    handler = artifact._storage_policy._handler._handlers["gs"]
    handler._client = mock
    return mock


def mock_http(artifact, path=False, headers={}):
    class Response(object):
        def __init__(self, headers):
            self.headers = headers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def raise_for_status(self):
            pass

    class Session(object):
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


def test_add_one_file(runner):
    with runner.isolated_filesystem():
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


def test_add_named_file(runner):
    with runner.isolated_filesystem():
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


def test_add_new_file(runner):
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        with artifact.new_file("file1.txt") as f:
            f.write("hello")

        assert artifact.digest == "a00c2239f036fb656c1dcbf9a32d89b4"
        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"]["file1.txt"] == {
            "digest": "XUFAKrxLKna5cZ2REBfFkg==",
            "size": 5,
        }


def test_add_dir(runner):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        artifact.add_dir(".")

        assert artifact.digest == "a00c2239f036fb656c1dcbf9a32d89b4"
        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"]["file1.txt"] == {
            "digest": "XUFAKrxLKna5cZ2REBfFkg==",
            "size": 5,
        }


def test_add_named_dir(runner):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        artifact.add_dir(".", name="subdir")

        assert artifact.digest == "a757208d042e8627b2970d72a71bed5b"

        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"]["subdir/file1.txt"] == {
            "digest": "XUFAKrxLKna5cZ2REBfFkg==",
            "size": 5,
        }


def test_add_reference_local_file(runner):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
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


def test_add_reference_local_file_no_checksum(runner):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
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


def test_add_reference_local_dir(runner):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
        os.mkdir("nest")
        open("nest/file2.txt", "w").write("my")
        os.mkdir("nest/nest")
        open("nest/nest/file3.txt", "w").write("dude")

        artifact = wandb.Artifact(type="dataset", name="my-arty")
        artifact.add_reference("file://" + os.getcwd())

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


def test_add_reference_local_dir_no_checksum(runner):
    with runner.isolated_filesystem():
        path_1 = os.path.join("file1.txt")
        open(path_1, "w").write("hello")
        size_1 = os.path.getsize(path_1)

        path_2 = os.path.join("nest", "file2.txt")
        os.mkdir("nest")
        open(path_2, "w").write("my")
        size_2 = os.path.getsize(path_2)

        path_3 = os.path.join("nest", "nest", "file3.txt")
        os.mkdir("nest/nest")
        open(path_3, "w").write("dude")
        size_3 = os.path.getsize(path_3)

        artifact = wandb.Artifact(type="dataset", name="my-arty")
        artifact.add_reference("file://" + os.getcwd(), checksum=False)

        assert artifact.digest == "3d0e6471486eec5070cf9351bacaa103"
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


def test_add_reference_local_dir_with_name(runner):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
        os.mkdir("nest")
        open("nest/file2.txt", "w").write("my")
        os.mkdir("nest/nest")
        open("nest/nest/file3.txt", "w").write("dude")

        artifact = wandb.Artifact(type="dataset", name="my-arty")
        artifact.add_reference("file://" + os.getcwd(), name="top")

        assert artifact.digest == "f718baf2d4c910dc6ccd0d9c586fa00f"
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


def test_add_s3_reference_object(runner, mocker):
    with runner.isolated_filesystem():
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


def test_add_s3_reference_object_with_name(runner, mocker):
    with runner.isolated_filesystem():
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


@pytest.mark.skipif(
    sys.version_info >= (3, 9), reason="botocore doesnt support py3.9 yet"
)
def test_add_s3_reference_path(runner, mocker, capsys):
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


@pytest.mark.skipif(
    sys.version_info >= (3, 9), reason="botocore doesnt support py3.9 yet"
)
def test_add_s3_max_objects(runner, mocker, capsys):
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        mock_boto(artifact, path=True)
        with pytest.raises(ValueError):
            artifact.add_reference("s3://my-bucket/", max_objects=1)


def test_add_reference_s3_no_checksum(runner):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        # TODO: Should we require name in this case?
        artifact.add_reference("s3://my_bucket/file1.txt", checksum=False)

        assert artifact.digest == "52631787ed3579325f985dc0f2374040"
        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"]["file1.txt"] == {
            "digest": "s3://my_bucket/file1.txt",
            "ref": "s3://my_bucket/file1.txt",
        }


def test_add_gs_reference_object(runner, mocker):
    with runner.isolated_filesystem():
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


def test_add_gs_reference_object_with_name(runner, mocker):
    with runner.isolated_filesystem():
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


def test_add_gs_reference_path(runner, mocker, capsys):
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


def test_add_http_reference_path(runner):
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        mock_http(artifact, headers={"ETag": '"abc"', "Content-Length": "256",})
        artifact.add_reference("http://example.com/file1.txt")

        assert artifact.digest == "48237ccc050a88af9dcd869dd5a7e9f4"
        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"]["file1.txt"] == {
            "digest": "abc",
            "ref": "http://example.com/file1.txt",
            "size": 256,
            "extra": {"etag": '"abc"',},
        }


def test_add_reference_named_local_file(runner):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        artifact.add_reference("file://file1.txt", name="great-file.txt")

        assert artifact.digest == "585b9ada17797e37c9cbab391e69b8c5"
        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"]["great-file.txt"] == {
            "digest": "XUFAKrxLKna5cZ2REBfFkg==",
            "ref": "file://file1.txt",
            "size": 5,
        }


def test_add_reference_unknown_handler(runner):
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        artifact.add_reference("ref://example.com/somefile.txt", name="ref")

        assert artifact.digest == "410ade94865e89ebe1f593f4379ac228"

        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"]["ref"] == {
            "digest": "ref://example.com/somefile.txt",
            "ref": "ref://example.com/somefile.txt",
        }


def test_add_table_from_dataframe(live_mock_server, test_settings):
    df_float = pd.DataFrame([[1, 2.0, 3.0]], dtype=np.float)
    df_float32 = pd.DataFrame([[1, 2.0, 3.0]], dtype=np.float32)
    df_bool = pd.DataFrame([[True, False, True]], dtype=np.bool)

    wb_table_float = wandb.Table(dataframe=df_float)
    wb_table_float32 = wandb.Table(dataframe=df_float32)
    wb_table_float32_recast = wandb.Table(dataframe=df_float32.astype(np.float))
    wb_table_bool = wandb.Table(dataframe=df_bool)

    run = wandb.init(settings=test_settings)
    artifact = wandb.Artifact("table-example", "dataset")
    artifact.add(wb_table_float, "wb_table_float")
    artifact.add(wb_table_float32_recast, "wb_table_float32_recast")
    artifact.add(wb_table_float32, "wb_table_float32")
    artifact.add(wb_table_bool, "wb_table_bool")
    run.log_artifact(artifact)
    run.finish()


@pytest.mark.timeout(120)
def test_artifact_log_with_network_error(live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)
    artifact = wandb.Artifact("table-example", "dataset")
    live_mock_server.set_ctx({"fail_graphql_times": 15})
    run.log_artifact(artifact)
    live_mock_server.set_ctx({"fail_graphql_times": 0})
    run.finish()


def test_add_obj_wbimage_no_classes(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(
            im_path,
            masks={
                "ground_truth": {
                    "path": os.path.join(test_folder, "..", "assets", "2x2.png"),
                },
            },
        )
        with pytest.raises(ValueError):
            artifact.add(wb_image, "my-image")


def test_add_obj_wbimage(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        artifact.add(wb_image, "my-image")

        manifest = artifact.manifest.to_manifest_json()
        assert artifact.digest == "a538083d89e2f5f0feafe5bb70cbb01c"
        assert manifest["contents"] == {
            "media/cls.classes.json": {
                "digest": "eG00DqdCcCBqphilriLNfw==",
                "size": 64,
            },
            "media/images/641e917f31888a48f546/2x2.png": {
                "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
                "size": 71,
            },
            "my-image.image-file.json": {
                "digest": "Vkp5lFFm5BClkm+ljIIt+g==",
                "size": 305,
            },
        }


def test_add_obj_using_brackets(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        artifact["my-image"] = wb_image

        manifest = artifact.manifest.to_manifest_json()
        assert artifact.digest == "a538083d89e2f5f0feafe5bb70cbb01c"
        assert manifest["contents"] == {
            "media/cls.classes.json": {
                "digest": "eG00DqdCcCBqphilriLNfw==",
                "size": 64,
            },
            "media/images/641e917f31888a48f546/2x2.png": {
                "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
                "size": 71,
            },
            "my-image.image-file.json": {
                "digest": "Vkp5lFFm5BClkm+ljIIt+g==",
                "size": 305,
            },
        }

    with pytest.raises(ValueError):
        image = artifact["my-image"]


def test_artifact_interface_get_item():
    art = wandb.wandb_sdk.interface.artifacts.Artifact()
    with pytest.raises(NotImplementedError):
        image = art["my-image"]


def test_artifact_interface_set_item():
    art = wandb.wandb_sdk.interface.artifacts.Artifact()
    with pytest.raises(NotImplementedError):
        art["my-image"] = 1


def test_duplicate_wbimage_from_file(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path_1 = os.path.join(test_folder, "..", "assets", "test.png")
    im_path_2 = os.path.join(test_folder, "..", "assets", "test2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="artifact")
        wb_image_1 = wandb.Image(im_path_1)
        wb_image_2 = wandb.Image(im_path_2)
        artifact.add(wb_image_1, "my-image_1")
        artifact.add(wb_image_2, "my-image_2")
        assert len(artifact.manifest.entries) == 4

    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="artifact")
        wb_image_1 = wandb.Image(im_path_1)
        wb_image_2 = wandb.Image(im_path_1)
        artifact.add(wb_image_1, "my-image_1")
        artifact.add(wb_image_2, "my-image_2")
        assert len(artifact.manifest.entries) == 3


def test_deduplicate_wbimage_from_array(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_data_1 = np.random.rand(300, 300, 3)
    im_data_2 = np.random.rand(300, 300, 3)
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="artifact")
        wb_image_1 = wandb.Image(im_data_1)
        wb_image_2 = wandb.Image(im_data_2)
        artifact.add(wb_image_1, "my-image_1")
        artifact.add(wb_image_2, "my-image_2")
        assert len(artifact.manifest.entries) == 4

    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="artifact")
        wb_image_1 = wandb.Image(im_data_1)
        wb_image_2 = wandb.Image(im_data_2)
        wb_image_3 = wandb.Image(im_data_1)  # yes, should be 1
        artifact.add(wb_image_1, "my-image_1")
        artifact.add(wb_image_2, "my-image_2")
        artifact.add(wb_image_3, "my-image_3")
        assert len(artifact.manifest.entries) == 5


def test_deduplicate_wbimagemask_from_array(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_data_1 = np.random.randint(0, 10, (300, 300))
    im_data_2 = np.random.randint(0, 10, (300, 300))
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="artifact")
        wb_imagemask_1 = data_types.ImageMask({"mask_data": im_data_1}, key="test")
        wb_imagemask_2 = data_types.ImageMask({"mask_data": im_data_2}, key="test2")
        artifact.add(wb_imagemask_1, "my-imagemask_1")
        artifact.add(wb_imagemask_2, "my-imagemask_2")
        assert len(artifact.manifest.entries) == 4

    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="artifact")
        wb_imagemask_1 = data_types.ImageMask({"mask_data": im_data_1}, key="test")
        wb_imagemask_2 = data_types.ImageMask({"mask_data": im_data_1}, key="test2")
        artifact.add(wb_imagemask_1, "my-imagemask_1")
        artifact.add(wb_imagemask_2, "my-imagemask_2")
        assert len(artifact.manifest.entries) == 3


def test_add_obj_wbimage_classes_obj(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        classes = wandb.Classes([{"id": 0, "name": "person"}])
        wb_image = wandb.Image(im_path, classes=classes)
        artifact.add(wb_image, "my-image")

        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"] == {
            "media/cls.classes.json": {
                "digest": "eG00DqdCcCBqphilriLNfw==",
                "size": 64,
            },
            "media/images/641e917f31888a48f546/2x2.png": {
                "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
                "size": 71,
            },
            "my-image.image-file.json": {
                "digest": "Vkp5lFFm5BClkm+ljIIt+g==",
                "size": 305,
            },
        }


def test_add_obj_wbimage_classes_obj_already_added(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "2x2.png")
    with runner.isolated_filesystem():
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
            "media/images/641e917f31888a48f546/2x2.png": {
                "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
                "size": 71,
            },
            "my-image.image-file.json": {
                "digest": "4IA8mYMQrmtyGGPj/Azdpg==",
                "size": 306,
            },
        }


def test_add_obj_wbimage_image_already_added(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        artifact.add_file(im_path)
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        artifact.add(wb_image, "my-image")

        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"] == {
            "2x2.png": {"digest": "L1pBeGPxG+6XVRQk4WuvdQ==", "size": 71},
            "media/cls.classes.json": {
                "digest": "eG00DqdCcCBqphilriLNfw==",
                "size": 64,
            },
            "my-image.image-file.json": {
                "digest": "8ZJmhiCv9lrjXBCz5oVl8g==",
                "size": 271,
            },
        }


def test_add_obj_wbtable_images(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        wb_table = wandb.Table(["examples"])
        wb_table.add_data(wb_image)
        wb_table.add_data(wb_image)
        artifact.add(wb_table, "my-table")

        manifest = artifact.manifest.to_manifest_json()

        assert manifest["contents"] == {
            "media/cls.classes.json": {
                "digest": "eG00DqdCcCBqphilriLNfw==",
                "size": 64,
            },
            "media/images/641e917f31888a48f546/2x2.png": {
                "digest": u"L1pBeGPxG+6XVRQk4WuvdQ==",
                "size": 71,
            },
            "my-table.table.json": {"digest": "8zWFSUyPI7j8c3+Wo0/EXQ==", "size": 1035},
        }


def test_add_obj_wbtable_images_duplicate_name(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    img_1 = os.path.join(test_folder, "..", "assets", "2x2.png")
    img_2 = os.path.join(test_folder, "..", "assets", "test.png")
    with runner.isolated_filesystem():
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
            "my-table.table.json": {"digest": "hT/A7Ugr75OmC+V1ru4zoA==", "size": 821},
        }


def test_artifact_upsert_no_id(runner, live_mock_server, test_settings):
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = "distributed_artifact_{}".format(round(time.time()))
    group_name = "test_group_{}".format(round(np.random.rand()))
    artifact_type = "dataset"

    # Upsert without a group or id should fail
    run = wandb.init(settings=test_settings)
    artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
    image = wandb.Image(np.random.randint(0, 255, (10, 10)))
    artifact.add(image, "image_1")
    with pytest.raises(TypeError):
        run.upsert_artifact(artifact)
    run.finish()


def test_artifact_upsert_group_id(runner, live_mock_server, test_settings):
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = "distributed_artifact_{}".format(round(time.time()))
    group_name = "test_group_{}".format(round(np.random.rand()))
    artifact_type = "dataset"

    # Upsert with a group should succeed
    run = wandb.init(group=group_name, settings=test_settings)
    artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
    image = wandb.Image(np.random.randint(0, 255, (10, 10)))
    artifact.add(image, "image_1")
    run.upsert_artifact(artifact)
    run.finish()


def test_artifact_upsert_distributed_id(runner, live_mock_server, test_settings):
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = "distributed_artifact_{}".format(round(time.time()))
    group_name = "test_group_{}".format(round(np.random.rand()))
    artifact_type = "dataset"

    # Upsert with a distributed_id should succeed
    run = wandb.init(settings=test_settings)
    artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
    image = wandb.Image(np.random.randint(0, 255, (10, 10)))
    artifact.add(image, "image_2")
    run.upsert_artifact(artifact, distributed_id=group_name)
    run.finish()


def test_artifact_finish_no_id(runner, live_mock_server, test_settings):
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = "distributed_artifact_{}".format(round(time.time()))
    group_name = "test_group_{}".format(round(np.random.rand()))
    artifact_type = "dataset"

    # Finish without a distributed_id should fail
    run = wandb.init(settings=test_settings)
    artifact = wandb.Artifact(artifact_name, type=artifact_type)
    with pytest.raises(TypeError):
        run.finish_artifact(artifact)
    run.finish()


def test_artifact_finish_group_id(runner, live_mock_server, test_settings):
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = "distributed_artifact_{}".format(round(time.time()))
    group_name = "test_group_{}".format(round(np.random.rand()))
    artifact_type = "dataset"

    # Finish with a distributed_id should succeed
    run = wandb.init(group=group_name, settings=test_settings)
    artifact = wandb.Artifact(artifact_name, type=artifact_type)
    run.finish_artifact(artifact)
    run.finish()


def test_artifact_finish_distributed_id(runner, live_mock_server, test_settings):
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = "distributed_artifact_{}".format(round(time.time()))
    group_name = "test_group_{}".format(round(np.random.rand()))
    artifact_type = "dataset"

    # Finish with a distributed_id should succeed
    run = wandb.init(settings=test_settings)
    artifact = wandb.Artifact(artifact_name, type=artifact_type)
    run.finish_artifact(artifact, distributed_id=group_name)
    run.finish()


def test_add_partition_folder(runner):
    with runner.isolated_filesystem():
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


def test_interface_commit_hash(runner):
    artifact = wandb.wandb_sdk.interface.artifacts.Artifact()
    with pytest.raises(NotImplementedError):
        artifact.commit_hash()


# this test hangs, which seems to be the result of incomplete mocks.
# would be worth returning to it in the future
# def test_artifact_incremental(runner, live_mock_server, parse_ctx, test_settings):
#     with runner.isolated_filesystem():
#         open("file1.txt", "w").write("hello")
#         run = wandb.init(settings=test_settings)
#         artifact = wandb.Artifact(type="dataset", name="incremental_test_PENDING", incremental=True)
#         artifact.add_file("file1.txt")
#         run.log_artifact(artifact)
#         run.finish()

#         manifests_created = parse_ctx(live_mock_server.get_ctx()).manifests_created
#         assert manifests_created[0]["type"] == "INCREMENTAL"


def test_artifact_incremental_internal(
    mocked_run, mock_server, internal_sm, backend_interface, parse_ctx,
):
    artifact = wandb.Artifact("incremental_test_PENDING", "dataset", incremental=True)

    with backend_interface() as interface:
        proto_run = interface._make_run(mocked_run)
        r = internal_sm.send_run(interface._make_record(run=proto_run))

        proto_artifact = interface._make_artifact(artifact)
        proto_artifact.run_id = proto_run.run_id
        proto_artifact.project = proto_run.project
        proto_artifact.entity = proto_run.entity
        proto_artifact.user_created = False
        proto_artifact.use_after_commit = False
        proto_artifact.finalize = True
        for alias in ["latest"]:
            proto_artifact.aliases.append(alias)
        log_artifact = pb.LogArtifactRequest()
        log_artifact.artifact.CopyFrom(proto_artifact)

        art = internal_sm.send_artifact(log_artifact)

    manifests_created = parse_ctx(mock_server.ctx).manifests_created
    assert manifests_created[0]["type"] == "INCREMENTAL"


def test_local_references(runner, live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)

    def make_table():
        return wandb.Table(columns=[], data=[])

    t1 = make_table()
    artifact1 = wandb.Artifact("test_local_references", "dataset")
    artifact1.add(t1, "t1")
    assert artifact1.manifest.entries["t1.table.json"].ref is None
    run.log_artifact(artifact1)
    artifact2 = wandb.Artifact("test_local_references_2", "dataset")
    artifact2.add(t1, "t2")
    assert artifact2.manifest.entries["t2.table.json"].ref is not None


def test_artifact_references_internal(
    mocked_run, mock_server, internal_sm, backend_interface, parse_ctx, test_settings,
):
    mock_server.set_context("max_cli_version", "0.11.0")
    run = wandb.init(settings=test_settings)
    t1 = wandb.Table(columns=[], data=[])
    art = wandb.Artifact("A", "dataset")
    art.add(t1, "t1")
    run.log_artifact(art)
    run.finish()

    art = wandb.Artifact("A_PENDING", "dataset")
    art.add(t1, "t1")

    with backend_interface() as interface:
        proto_run = interface._make_run(mocked_run)
        r = internal_sm.send_run(interface._make_record(run=proto_run))

        proto_artifact = interface._make_artifact(art)
        proto_artifact.run_id = proto_run.run_id
        proto_artifact.project = proto_run.project
        proto_artifact.entity = proto_run.entity
        proto_artifact.user_created = False
        proto_artifact.use_after_commit = False
        proto_artifact.finalize = True
        for alias in ["latest"]:
            proto_artifact.aliases.append(alias)
        log_artifact = pb.LogArtifactRequest()
        log_artifact.artifact.CopyFrom(proto_artifact)

        art = internal_sm.send_artifact(log_artifact)


def test_lazy_artifact_passthrough(runner, live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)
    t1 = wandb.Table(columns=[], data=[])
    art = wandb.Artifact("test_lazy_artifact_passthrough", "dataset")
    e = art.add(t1, "t1")

    with pytest.raises(ValueError):
        e.ref_target()

    # These properties should be valid both before and after logging
    testable_getters_valid = [
        "id",
        "entity",
        "project",
        "manifest",
        "digest",
        "type",
        "name",
        "state",
        "size",
        "description",
        "metadata",
    ]

    # These are valid even before waiting!
    testable_getters_always_valid = ["distributed_id"]

    # These properties should be valid only after logging
    testable_getters_invalid = ["version", "commit_hash", "aliases"]

    # These setters should be valid both before and after logging
    testable_setters_valid = ["description", "metadata"]

    # These are valid even before waiting!
    testable_setters_always_valid = ["distributed_id"]

    # These setters should be valid only after logging
    testable_setters_invalid = ["aliases"]

    # These methods should be valid both before and after logging
    testable_methods_valid = ["save"]

    # These methods should be valid only after logging
    testable_methods_invalid = [
        "used_by",
        "logged_by",
        "get_path",
        "get",
        "download",
        "checkout",
        "verify",
        "delete",
    ]

    setter_data = {"metadata": {}}
    params = {"get_path": ["t1.table.json"], "get": ["t1"]}

    # these are failures of mocking
    special_errors = {
        "verify": ValueError,
        "logged_by": KeyError,
    }

    for valid_getter in testable_getters_valid + testable_getters_always_valid:
        _ = getattr(art, valid_getter)

    for invalid_getter in testable_getters_invalid:
        with pytest.raises(ValueError):
            _ = getattr(art, invalid_getter)

    for valid_setter in testable_setters_valid + testable_setters_always_valid:
        setattr(art, valid_setter, setter_data.get(valid_setter, valid_setter))

    for invalid_setter in testable_setters_invalid:
        with pytest.raises(ValueError):
            setattr(
                art, invalid_setter, setter_data.get(invalid_setter, invalid_setter)
            )

    # Uncomment if there are ever entries in testable_methods_valid
    # leaving commented for now since test coverage wants all lines to
    # run
    # for valid_method in testable_methods_valid:
    #     attr_method = getattr(art, valid_method)
    #     _ = attr_method(*params.get(valid_method, []))

    for invalid_method in testable_methods_invalid:
        attr_method = getattr(art, invalid_method)
        with pytest.raises(ValueError):
            _ = attr_method(*params.get(invalid_method, []))

    # THE LOG
    run.log_artifact(art)

    for getter in testable_getters_valid + testable_getters_invalid:
        with pytest.raises(ValueError):
            _ = getattr(art, getter)

    for setter in testable_setters_valid + testable_setters_invalid:
        with pytest.raises(ValueError):
            setattr(art, setter, "TEST")

    for method in testable_methods_valid + testable_methods_invalid:
        attr_method = getattr(art, method)
        with pytest.raises(ValueError):
            _ = attr_method(*params.get(method, []))

    # THE ALL IMPORTANT WAIT
    art.wait()

    for getter in testable_getters_valid + testable_getters_invalid:
        _ = getattr(art, getter)

    for setter in testable_setters_valid + testable_setters_invalid:
        setattr(art, setter, "TEST")

    for method in testable_methods_valid + testable_methods_invalid:
        attr_method = getattr(art, method)
        if method in special_errors:
            with pytest.raises(special_errors[method]):
                _ = attr_method(*params.get(method, []))
        else:
            _ = attr_method(*params.get(method, []))


def test_reference_download(runner, live_mock_server, test_settings):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
        run = wandb.init(settings=test_settings)
        artifact = wandb.Artifact("test_reference_download", "dataset")
        artifact.add_file("file1.txt")
        artifact.add_reference(
            "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
        )
        run.log_artifact(artifact)
        run.finish()

        run = wandb.init(settings=test_settings)
        artifact = run.use_artifact("my-test_reference_download:latest")
        entry = artifact.get_path("StarWars3.wav")
        entry.download()
        assert (
            entry.ref_target()
            == "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
        )

        entry = artifact.get_path("file1.txt")
        entry.download()
        with pytest.raises(ValueError):
            assert entry.ref_target()
        run.finish()


def test_communicate_artifact(publish_util, mocked_run):
    artifact = wandb.Artifact("comms_test_PENDING", "dataset")
    artifact_publish = dict(run=mocked_run, artifact=artifact, aliases=["latest"])
    ctx_util = publish_util(artifacts=[artifact_publish])
    assert len(set(ctx_util.manifests_created_ids)) == 1
