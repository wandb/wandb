# Suggest running as: WANDB_BASE_URL=http://api.wandb.test python artifact_object_reference_test.py                                                               timothysweeney@Timothys-MacBook-Pro
import shutil
import wandb
import os
import binascii
import base64
import time
import numpy as np

PROJECT_NAME = "test__" + str(round(time.time()) % 1000000)


columns = ["id", "bool", "int", "float", "Image"]

def _make_wandb_image(suffix=""):
    class_labels = {1: "tree", 2: "car", 3: "road"}
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "test{}.png".format(suffix))
    return wandb.Image(
        im_path,
        classes=wandb.Classes([
        {"id": 0, "name": "tree"},
        {"id": 1, "name": "car"},
        {"id": 3, "name": "road"},
    ]),
        boxes={
            "predictions": {
                "box_data": [
                    {
                        "position": {
                            "minX": 0.1,
                            "maxX": 0.2,
                            "minY": 0.3,
                            "maxY": 0.4,
                        },
                        "class_id": 1,
                        "box_caption": "minMax(pixel)",
                        "scores": {"acc": 0.1, "loss": 1.2},
                    },
                    {
                        "position": {
                            "minX": 0.1,
                            "maxX": 0.2,
                            "minY": 0.3,
                            "maxY": 0.4,
                        },
                        "class_id": 2,
                        "box_caption": "minMax(pixel)",
                        "scores": {"acc": 0.1, "loss": 1.2},
                    },
                ],
                "class_labels": class_labels,
            },
            "ground_truth": {
                "box_data": [
                    {
                        "position": {
                            "minX": 0.1,
                            "maxX": 0.2,
                            "minY": 0.3,
                            "maxY": 0.4,
                        },
                        "class_id": 1,
                        "box_caption": "minMax(pixel)",
                        "scores": {"acc": 0.1, "loss": 1.2},
                    },
                    {
                        "position": {
                            "minX": 0.1,
                            "maxX": 0.2,
                            "minY": 0.3,
                            "maxY": 0.4,
                        },
                        "class_id": 2,
                        "box_caption": "minMax(pixel)",
                        "scores": {"acc": 0.1, "loss": 1.2},
                    },
                ],
                "class_labels": class_labels,
            },
        },
        masks={
            "predictions": {
                "mask_data": np.random.randint(0, 4, size=(30, 30)),
                "class_labels": class_labels,
            },
            "ground_truth": {"path": im_path, "class_labels": class_labels},
        },
    )


def _make_wandb_table():
    return wandb.Table(
        columns=columns,
        data=[
            ["string", True, 1, 1.4, _make_wandb_image()],
            ["string", True, 1, 1.4, _make_wandb_image()],
            ["string2", False, -0, -1.4, _make_wandb_image("2")],
            ["string2", False, -0, -1.4, _make_wandb_image("2")],
        ],
    )

def _make_wandb_joinedtable():
    return wandb.JoinedTable(_make_wandb_table(), _make_wandb_table(), "id")


def _b64_to_hex_id(id_string):
    return binascii.hexlify(base64.standard_b64decode(str(id_string))).decode("utf-8")

# Artifact1.add_reference(artifact_URL) => recursive reference
def test_artifact_add_reference_via_url():
    """ This test creates three artifacts. The middle artifact references the first artifact's file,
    and the last artifact references the middle artifact's reference. The end result of downloading
    the last artifact in a fresh, forth run, should be that all 3 artifacts are downloaded and that
    the file in the last artifact is actually a symlink to the first artifact's file.
    """
    upstream_artifact_name = "upstream_artifact"
    middle_artifact_name = "middle_artifact"
    downstream_artifact_name = "downstream_artifact"

    upstream_local_path = "upstream/local/path/"

    upstream_artifact_path = "upstream/artifact/path/"
    middle_artifact_path = "middle/artifact/path/"
    downstream_artifact_path = "downstream/artifact/path/"

    upstream_local_file_path = upstream_local_path + "file.txt"
    upstream_artifact_file_path = upstream_artifact_path + "file.txt"
    middle_artifact_file_path = middle_artifact_path + "file.txt"
    downstream_artifact_file_path = downstream_artifact_path + "file.txt"

    file_text = "Luke, I am your Father!!!!!"
    # Create a super important file
    os.makedirs(upstream_local_path, exist_ok=True)
    with open(upstream_local_file_path, "w") as file:
        file.write(file_text)

    # Create an artifact with such file stored
    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact(upstream_artifact_name, "database")
        artifact.add_file(upstream_local_file_path, upstream_artifact_file_path)
        run.log_artifact(artifact)

    # Create an middle artifact with such file referenced (notice no need to download)
    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact(middle_artifact_name, "database")
        upstream_artifact = run.use_artifact(upstream_artifact_name + ":latest")
        artifact.add_reference(
            "wandb-artifact://{}/{}".format(_b64_to_hex_id(upstream_artifact.id),str(upstream_artifact_file_path)),
            middle_artifact_file_path,
        )
        run.log_artifact(artifact)

    # Create a downstream artifact that is referencing the middle's reference
    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact(downstream_artifact_name, "database")
        middle_artifact = run.use_artifact(middle_artifact_name + ":latest")
        artifact.add_reference(
            "wandb-artifact://{}/{}".format(_b64_to_hex_id(middle_artifact.id),str(middle_artifact_file_path)),
            downstream_artifact_file_path,
        )
        run.log_artifact(artifact)

    # Remove the directories for good measure
    if os.path.isdir("upstream"):
        shutil.rmtree("upstream")
    if os.path.isdir("artifacts"):
        shutil.rmtree("artifacts")

    # Finally, use the artifact (download it) and enforce that the file is where we want it!
    with wandb.init(project=PROJECT_NAME) as run:
        downstream_artifact = run.use_artifact(downstream_artifact_name + ":latest")
        downstream_path = downstream_artifact.download()
        # assert os.path.islink(
        #     os.path.join(downstream_path, downstream_artifact_file_path)
        # )
        with open(
            os.path.join(downstream_path, downstream_artifact_file_path), "r"
        ) as file:
            assert file.read() == file_text


# # Artifact1.add_reference(artifact2.get_path(file_name))
def test_add_reference_via_artifact_entry():
    """This test is the same as test_artifact_add_reference_via_url, but rather
    than passing the direct URL, we pass an Artifact entry, which will automatically
    resolve to the correct URL
    """
    upstream_artifact_name = "upstream_artifact"
    middle_artifact_name = "middle_artifact"
    downstream_artifact_name = "downstream_artifact"

    upstream_local_path = "upstream/local/path/"

    upstream_artifact_path = "upstream/artifact/path/"
    middle_artifact_path = "middle/artifact/path/"
    downstream_artifact_path = "downstream/artifact/path/"

    upstream_local_file_path = upstream_local_path + "file.txt"
    upstream_artifact_file_path = upstream_artifact_path + "file.txt"
    middle_artifact_file_path = middle_artifact_path + "file.txt"
    downstream_artifact_file_path = downstream_artifact_path + "file.txt"

    file_text = "Luke, I am your Father!!!!!"
    # Create a super important file
    os.makedirs(upstream_local_path, exist_ok=True)
    with open(upstream_local_file_path, "w") as file:
        file.write(file_text)

    # Create an artifact with such file stored
    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact(upstream_artifact_name, "database")
        artifact.add_file(upstream_local_file_path, upstream_artifact_file_path)
        run.log_artifact(artifact)

    # Create an middle artifact with such file referenced (notice no need to download)
    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact(middle_artifact_name, "database")
        upstream_artifact = run.use_artifact(upstream_artifact_name + ":latest")
        artifact.add_reference(
            upstream_artifact.get_path(upstream_artifact_file_path),
            middle_artifact_file_path,
        )
        run.log_artifact(artifact)

    # Create a downstream artifact that is referencing the middle's reference
    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact(downstream_artifact_name, "database")
        middle_artifact = run.use_artifact(middle_artifact_name + ":latest")
        artifact.add_reference(
            middle_artifact.get_path(middle_artifact_file_path),
            downstream_artifact_file_path,
        )
        run.log_artifact(artifact)

    # Remove the directories for good measure
    if os.path.isdir("upstream"):
        shutil.rmtree("upstream")
    if os.path.isdir("artifacts"):
        shutil.rmtree("artifacts")

    # Finally, use the artifact (download it) and enforce that the file is where we want it!
    with wandb.init(project=PROJECT_NAME) as run:
        downstream_artifact = run.use_artifact(downstream_artifact_name + ":latest")
        downstream_path = downstream_artifact.download()
        downstream_path = downstream_artifact.download() # should not fail on second download.
        # assert os.path.islink(
        #     os.path.join(downstream_path, downstream_artifact_file_path)
        # )
        with open(
            os.path.join(downstream_path, downstream_artifact_file_path), "r"
        ) as file:
            assert file.read() == file_text

# # Artifact1.get(MEDIA_NAME) => media obj
def test_get_artifact_obj_by_name():
    """Tests tests the ability to instantiate a wandb Media object when passed
    the name of such object. This is the logical inverse of Artifact.add(name).
    TODO: test more robustly for every Media type, nested objects (eg. Table -> Image),
    and references
    """

    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact("A2", "database")
        image = _make_wandb_image()
        table = _make_wandb_table()
        artifact.add(image, "I1")
        artifact.add(table, "T1")
        run.log_artifact(artifact)

    with wandb.init(project=PROJECT_NAME) as run:
        artifact = run.use_artifact("A2:latest")
        actual_image = artifact.get("I1")
        assert actual_image == image

        actual_table = artifact.get("T1")
        assert actual_table.columns == columns
        assert actual_table.data[0][4] == image
        assert actual_table.data[1][4] == _make_wandb_image("2")
        assert actual_table == _make_wandb_table()


# # Artifact1.add(artifact2.get(MEDIA_NAME))
def test_adding_artifact_by_object():
    """This test validates that we can add wandb Media objects
    to an artifact by passing the object itself.
    """
    # Create an artifact with such file stored
    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact("upstream_media", "database")
        artifact.add(_make_wandb_image(), "I1")
        run.log_artifact(artifact)

    # Create an middle artifact with such file referenced (notice no need to download)
    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact("downstream_media", "database")
        upstream_artifact = run.use_artifact("upstream_media:latest")
        artifact.add(upstream_artifact.get("I1"), "T2")
        run.log_artifact(artifact)

    if os.path.isdir("artifacts"):
        shutil.rmtree("artifacts")

    with wandb.init(project=PROJECT_NAME) as run:
        downstream_artifact = run.use_artifact("downstream_media:latest")
        downstream_path = downstream_artifact.download()
        # assert os.path.islink(os.path.join(downstream_path, "T2.image-file.json"))
        assert downstream_artifact.get("T2") == _make_wandb_image()

def _cleanup():
    if os.path.isdir("wandb"):
        shutil.rmtree("wandb")
    if os.path.isdir("artifacts"):
        shutil.rmtree("artifacts")
    if os.path.isdir("upstream"):
        shutil.rmtree("upstream")


def test_image_reference_artifact():
    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact("image_data", "data")
        image = _make_wandb_image()
        artifact.add(image, "image")
        run.log_artifact(artifact)

    with wandb.init(project=PROJECT_NAME) as run:
        artifact_1 = run.use_artifact("image_data:latest")
        artifact = wandb.Artifact("reference_data", "data")
        artifact.add(artifact_1.get("image"), "image_2")
        run.log_artifact(artifact)

    _cleanup()
    with wandb.init(project=PROJECT_NAME) as run:
        artifact_2 = run.use_artifact("reference_data:latest")
        artifact_2.download()
        # assert os.path.islink(os.path.join(artifact_2._default_root(), "image_2.image-file.json"))


def test_nested_reference_artifact():
    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact("image_data", "data")
        image = _make_wandb_image()
        artifact.add(image, "image")
        run.log_artifact(artifact)

    with wandb.init(project=PROJECT_NAME) as run:
        artifact_1 = run.use_artifact("image_data:latest")
        artifact = wandb.Artifact("reference_data", "data")
        table = wandb.Table(["image"], [[artifact_1.get("image")]])
        artifact.add(table, "table_2")
        run.log_artifact(artifact)

    with wandb.init(project=PROJECT_NAME) as run:
        artifact_3 = run.use_artifact("reference_data:latest")
        table_2 = artifact_3.get("table_2")
        # assert os.path.islink(os.path.join(artifact_3._default_root(), "media", "images", "test.png"))

    assert table == table_2


def test_table_slice_reference_artifact():
    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact("table_data", "data")
        table = _make_wandb_table()
        artifact.add(table, "table")
        run.log_artifact(artifact)

    with wandb.init(project=PROJECT_NAME) as run:
        artifact_1 = run.use_artifact("table_data:latest")
        t1 = artifact_1.get("table")
        artifact = wandb.Artifact("intermediate_data", "data")
        i1 = wandb.Table(t1.columns, t1.data[:1])
        i2 = wandb.Table(t1.columns, t1.data[1:])
        artifact.add(i1, "table1")
        artifact.add(i2, "table2")
        run.log_artifact(artifact)

    with wandb.init(project=PROJECT_NAME) as run:
        artifact_2 = run.use_artifact("intermediate_data:latest")
        i1 = artifact_2.get("table1")
        i2 = artifact_2.get("table2")
        artifact = wandb.Artifact("reference_data", "data")
        table1 = wandb.Table(t1.columns, i1.data)
        table2 = wandb.Table(t1.columns, i2.data)
        artifact.add(table1, "table1")
        artifact.add(table2, "table2")
        run.log_artifact(artifact)

    _cleanup()
    with wandb.init(project=PROJECT_NAME) as run:
        artifact_3 = run.use_artifact("reference_data:latest")
        table1 = artifact_3.get("table1")
        table2 = artifact_3.get("table2")
    
    assert not os.path.isdir(os.path.join(artifact_2._default_root()))
    # assert os.path.islink(os.path.join(artifact_3._default_root(), "media", "images", "test.png"))
    # assert os.path.islink(os.path.join(artifact_3._default_root(), "media", "images", "test2.png"))
    assert t1.data[:1] == table1.data
    assert t1.data[1:] == table2.data

# General helper function which will perform the following:
#   Add the object to an artifact
#       Validate that "getting" this asset returns an object that is equal to the first
#   Add a reference to this asset in an intermediate artifact
#       Validate that "getting" this reference asset returns an object that is equal to the first
#       Validate that the symbolic links are proper
#   Add a reference to the intermediate reference in yet a third artifact
#       Validate that "getting" this new reference asset returns an object that is equal to the first
#       Validate that the intermediate object is not downloaded - there are no "leftover" assets (eg. classes.json)
#       Validate that the symbolic links are proper
def assert_media_obj_referential_equality(obj):
    with wandb.init(project=PROJECT_NAME) as run:
        orig_artifact = wandb.Artifact("orig_artifact", "database")
        orig_artifact.add(obj, "obj")
        run.log_artifact(orig_artifact)

    _cleanup()
    with wandb.init(project=PROJECT_NAME) as run:
        orig_artifact_ref = run.use_artifact("orig_artifact:latest")
        orig_dir = orig_artifact_ref._default_root()
        obj1 = orig_artifact_ref.get("obj")

    assert obj1 == obj
    target_path = os.path.join(orig_dir, "obj." + type(obj).artifact_type + ".json")
    assert os.path.isfile(target_path)

    with wandb.init(project=PROJECT_NAME) as run:
        orig_artifact_ref = run.use_artifact("orig_artifact:latest")
        mid_artifact = wandb.Artifact("mid_artifact", "database")
        mid_obj = orig_artifact_ref.get("obj")
        mid_artifact.add(mid_obj, "obj2")
        run.log_artifact(mid_artifact)

    _cleanup()
    with wandb.init(project=PROJECT_NAME) as run:
        mid_artifact_ref = run.use_artifact("mid_artifact:latest")
        mid_dir = mid_artifact_ref._default_root()
        obj2 = mid_artifact_ref.get("obj2")

    assert obj2 == obj
    # name = "obj2." + type(obj).artifact_type + ".json"
    # start_path = os.path.join(mid_dir, name)
    # mid_artifact_ref.get_path(name).download()
    # assert os.path.islink(start_path)
    # assert os.path.abspath(os.readlink(start_path)) == os.path.abspath(target_path)

    with wandb.init(project=PROJECT_NAME) as run:
        mid_artifact_ref = run.use_artifact("mid_artifact:latest")
        down_artifact = wandb.Artifact("down_artifact", "database")
        down_obj = mid_artifact_ref.get("obj2")
        down_artifact.add(down_obj, "obj3")
        run.log_artifact(down_artifact)

    _cleanup()
    with wandb.init(project=PROJECT_NAME) as run:
        down_artifact_ref = run.use_artifact("down_artifact:latest")
        down_dir = down_artifact_ref._default_root()
        obj3 = down_artifact_ref.get("obj3")

    assert obj3 == obj
    assert not os.path.isdir(os.path.join(mid_dir))
    # name = "obj3." + type(obj).artifact_type + ".json"
    # start_path = os.path.join(down_dir, name)
    # down_artifact_ref.get_path(name).download()
    # assert os.path.islink(start_path)
    # assert os.path.abspath(os.readlink(start_path)) == os.path.abspath(target_path)


def test_table_refs():
    assert_media_obj_referential_equality(_make_wandb_table())


def test_image_refs():
    assert_media_obj_referential_equality(_make_wandb_image())


def test_joined_table_refs():
    assert_media_obj_referential_equality(_make_wandb_joinedtable())


def test_joined_table_referential():
    src_image_1 = _make_wandb_image()
    src_image_2 = _make_wandb_image()
    src_image_3 = _make_wandb_image()
    src_image_4 = _make_wandb_image()
    src_table_1 = wandb.Table(["id", "image"], [[1, src_image_1], [2, src_image_2]])
    src_table_2 = wandb.Table(["id", "image"], [[1, src_image_3], [2, src_image_4]])
    src_jt_1 = wandb.JoinedTable(src_table_1, src_table_2, "id")

    with wandb.init(project=PROJECT_NAME) as run:
        orig_artifact = wandb.Artifact("art1", "database")
        orig_artifact.add(src_jt_1, "src_jt_1")
        run.log_artifact(orig_artifact)

    with wandb.init(project=PROJECT_NAME) as run:
        art1 = run.use_artifact("art1:latest")
        src_jt_1 = art1.get("src_jt_1")
        src_jt_2 = wandb.JoinedTable(src_jt_1._table1, src_jt_1._table2, "id")
        art2 = wandb.Artifact("art2", "database")
        art2.add(src_jt_2, "src_jt_2")
        run.log_artifact(art2)

    _cleanup()
    with wandb.init(project=PROJECT_NAME) as run:
        art2 = run.use_artifact("art2:latest")
        src_jt_2 = art2.get("src_jt_2")
        assert src_jt_1 == src_jt_2


if __name__ == "__main__":
    _cleanup()
    for test_fn in [
        test_artifact_add_reference_via_url,
        test_add_reference_via_artifact_entry,
        test_adding_artifact_by_object,
        test_get_artifact_obj_by_name,
        test_image_reference_artifact,
        test_nested_reference_artifact,
        test_table_slice_reference_artifact,
        test_image_refs,
        test_table_refs,
        test_joined_table_refs,
        test_joined_table_referential,
    ]:
        try:
            test_fn()
            _cleanup()
        except Exception as exception:
            print("error on function {}".format(test_fn.__name__))
            raise exception
        # finally:
        #     _cleanup()
