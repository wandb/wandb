import os
import sys
import pytest
from wandb import util
import wandb
import shutil
import wandb.data_types as data_types
import numpy as np
import pandas as pd


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
        artifact.add_reference("file://file1.txt")

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
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        artifact.add_reference("file://file1.txt", checksum=False)

        assert artifact.digest == "2f66dd01e5aea4af52445f7602fe88a0"
        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"]["file1.txt"] == {
            "digest": "file://file1.txt",
            "ref": "file://file1.txt",
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
        assert artifact.digest == "14e7a694dd91e2cebe7a0638745f21ba"
        assert manifest["contents"] == {
            "media/cls.classes.json": {
                "digest": "eG00DqdCcCBqphilriLNfw==",
                "size": 64,
            },
            "media/images/641e917f/2x2.png": {
                "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
                "size": 71,
            },
            "my-image.image-file.json": {
                "digest": "caWKIWtOV96QLSx8Y3uwnw==",
                "size": 215,
            },
        }


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
            "media/images/641e917f/2x2.png": {
                "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
                "size": 71,
            },
            "my-image.image-file.json": {
                "digest": "caWKIWtOV96QLSx8Y3uwnw==",
                "size": 215,
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
            "media/images/641e917f/2x2.png": {
                "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
                "size": 71,
            },
            "my-image.image-file.json": {
                "digest": "ksQ+BJCt+KZSsyC03K2+Uw==",
                "size": 216,
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
                "digest": "ZeHjOyjSSVRwrmibiprSQw==",
                "size": 193,
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
            "media/images/641e917f/2x2.png": {
                "digest": u"L1pBeGPxG+6XVRQk4WuvdQ==",
                "size": 71,
            },
            "my-table.table.json": {"digest": "cdDElzSZxodt71nbTWNkVw==", "size": 857},
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
            "media/images/641e917f/img.png": {
                "digest": "L1pBeGPxG+6XVRQk4WuvdQ==",
                "size": 71,
            },
            "media/images/cf37c38f/img.png": {
                "digest": "pQVvBBgcuG+jTN0Xo97eZQ==",
                "size": 8837,
            },
            "my-table.table.json": {"digest": "QArBMeEZwF9gz3E27v1OXw==", "size": 643},
        }
