import os
import pytest
from wandb import util
import wandb
import platform
import shutil


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

        if platform.system() == "Windows":
            digest = "84eb4e81b4fe7ef81bd13971c6f80cdc"
        else:
            digest = "a757208d042e8627b2970d72a71bed5b"

        assert artifact.digest == digest

        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"][os.path.join("subdir", "file1.txt")] == {
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
        open("file2.txt", "w").write("dude")
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        artifact.add_reference("file://" + os.getcwd())

        assert artifact.digest == "5e8e98ebd59cc93b58d0cb26432d4720"
        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"]["file1.txt"] == {
            "digest": "XUFAKrxLKna5cZ2REBfFkg==",
            "ref": "file://" + os.path.join(os.getcwd(), "file1.txt"),
            "size": 5,
        }
        assert manifest["contents"]["file2.txt"] == {
            "digest": "E7c+2uhEOZC+GqjxpIO8Jw==",
            "ref": "file://" + os.path.join(os.getcwd(), "file2.txt"),
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


def test_add_obj_wbimage_no_classes(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(im_path, masks={
            "ground_truth": {
                "path": os.path.join(test_folder, "2x2.png"),
            },
        })
        with pytest.raises(ValueError):
            artifact.add(wb_image, "my-image")


def test_add_obj_wbimage(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        artifact.add(wb_image, "my-image")

        assert artifact.digest == "20de491de6fe059dce7d01011ccd50d9"

        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"] == {
            "classes.json": {"digest": "eG00DqdCcCBqphilriLNfw==", "size": 64},
            "media/images/2x2.png": {"digest": "L1pBeGPxG+6XVRQk4WuvdQ==", "size": 71},
            'my-image.image-file.json': {'digest': '4SDhgUz28S9eIL2l44r1QQ==', 'size': 196}
        }


def test_add_obj_wbimage_classes_obj(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        classes = wandb.Classes([{"id": 0, "name": "person"}])
        wb_image = wandb.Image(im_path, classes=classes)
        artifact.add(wb_image, "my-image")

        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"] == {
            "classes.json": {"digest": "eG00DqdCcCBqphilriLNfw==", "size": 64},
            "media/images/2x2.png": {"digest": "L1pBeGPxG+6XVRQk4WuvdQ==", "size": 71},
            'my-image.image-file.json': {'digest': '4SDhgUz28S9eIL2l44r1QQ==', 'size': 196},
        }


def test_add_obj_wbimage_classes_obj_already_added(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "2x2.png")
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
            "media/images/2x2.png": {"digest": "L1pBeGPxG+6XVRQk4WuvdQ==", "size": 71},
            'my-image.image-file.json': {'digest': 'V6nFpdY77fpMfHpBvKskiA==', 'size': 207},
        }


def test_add_obj_wbimage_image_already_added(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        artifact.add_file(im_path)
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        artifact.add(wb_image, "my-image")

        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"] == {
            "classes.json": {"digest": "eG00DqdCcCBqphilriLNfw==", "size": 64},
            "2x2.png": {"digest": "L1pBeGPxG+6XVRQk4WuvdQ==", "size": 71},
            'my-image.image-file.json': {'digest': 'jrWWP1XoW6ryRc0jrVHsvQ==', 'size': 183},
        }


def test_add_obj_wbtable_images(runner):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        wb_table = wandb.Table(["examples"])
        wb_table.add_data(wb_image)
        wb_table.add_data(wb_image)
        artifact.add(wb_table, "my-table")

        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"] == {
            "classes.json": {"digest": "eG00DqdCcCBqphilriLNfw==", "size": 64},
            "media/images/2x2.png": {"digest": "L1pBeGPxG+6XVRQk4WuvdQ==", "size": 71},
            'my-table.table.json': {'digest': 'jq0OCE0XvYFzhvwS17kD2w==', 'size': 459},
        }

# TODO (tim): Get the mocks working properly. For now, copy this into a notebook/file to test
# def test_artifact_add_reference_dependency(runner):
#     upstream_artifact_name = "upstream_artifact"
#     middle_artifact_name = "middle_artifact"
#     downstream_artifact_name = "downstream_artifact"

#     upstream_local_path = "upstream/local/path/"

#     upstream_artifact_path = "upstream/artifact/path/"
#     middle_artifact_path = "middle/artifact/path/"
#     downstream_artifact_path = "downstream/artifact/path/"

#     upstream_local_file_path = upstream_local_path + "file.txt"
#     upstream_artifact_file_path = upstream_artifact_path + "file.txt"
#     middle_artifact_file_path = middle_artifact_path + "file.txt"
#     downstream_artifact_file_path = downstream_artifact_path + "file.txt"

#     file_text = "Luke, I am your Father!!!!!"
#     ## Create a super important file
#     os.makedirs(upstream_local_path, exist_ok=True)
#     with open(upstream_local_file_path, "w") as file:
#         file.write(file_text)

#     ## Create an artifact with such file stored
#     with wandb.init(project="tester") as run:
#         artifact = wandb.Artifact(upstream_artifact_name, "database")
#         artifact.add_file(upstream_local_file_path, upstream_artifact_file_path)
#         run.log_artifact(artifact)

#     ## Create an middle artifact with such file referenced (notice no need to download)
#     with wandb.init(project="tester") as run:
#         artifact = wandb.Artifact(middle_artifact_name, "database")
#         upstream_artifact = run.use_artifact(upstream_artifact_name + ":latest")
#         artifact.add_reference("wandb-artifact://" + upstream_artifact.id + "/" + upstream_artifact_file_path, middle_artifact_file_path)
#         run.log_artifact(artifact)

#     # Create a downstream artifact that is referencing the middle's reference
#     with wandb.init(project="tester") as run:
#         artifact = wandb.Artifact(downstream_artifact_name, "database")
#         middle_artifact = run.use_artifact(middle_artifact_name+":latest")
#         artifact.add_reference("wandb-artifact://" + middle_artifact.id + "/" + middle_artifact_file_path, downstream_artifact_file_path)
#         run.log_artifact(artifact)

#     ## Remove the directories for good measure
#     if os.path.isdir("upstream"):
#         shutil.rmtree("upstream")
#     if os.path.isdir("artifacts"):
#         shutil.rmtree("artifacts")

#     ## Finally, use the artifact (download it) and enforce that the file is where we want it!
#     with wandb.init(project="tester") as run:
#         downstream_artifact = run.use_artifact(downstream_artifact_name + ":latest")
#         downstream_path = downstream_artifact.download()
#         assert os.path.islink(os.path.join(downstream_path, downstream_artifact_file_path))
#         with open(os.path.join(downstream_path, downstream_artifact_file_path), "r") as file:
#             assert file.read() == file_text


# classes = [{"id": 0, "name": "person"}]
# columns = ["examples", "index"]

# def _make_wandb_image(suffix=""):
#     return wandb.Image("test"+str(suffix)+".png", classes=classes)

# def _assert_wandb_image_compare(image, suffix=""):
#     assert isinstance(image, wandb.Image)
#     assert image._image == _make_wandb_image(suffix)._image
#     assert image._classes._class_set == classes

# def _make_wandb_table():
#     table = wandb.Table(columns)
#     table.add_data(_make_wandb_image(), 1)
#     table.add_data(_make_wandb_image(2), 2)
#     return table

# def _make_joined_table():
#     table_1 = _make_wandb_table()
#     table_2 = _make_wandb_table()
#     return wandb.JoinedTable(table_1, table_2, "index")

# with wandb.init(project="tester") as run:
#     artifact = wandb.Artifact("A2", "database")
#     image = _make_wandb_image()
#     table = _make_wandb_table()
#     artifact.add(image, "I1")
#     artifact.add(table, "T1")
#     run.log_artifact(artifact)

# with wandb.init(project="tester") as run:
#     artifact = run.use_artifact("A2:latest")
#     actual_image = artifact.get_obj("I1")
#     _assert_wandb_image_compare(actual_image)
    
#     actual_table = artifact.get_obj("T1")
#     assert actual_table.columns == columns
#     _assert_wandb_image_compare(actual_table.data[0][0])
#     _assert_wandb_image_compare(actual_table.data[1][0], "2")
#     assert actual_table.data[0][1] == 1
#     assert actual_table.data[1][1] == 2