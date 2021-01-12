# Suggest running as: WANDB_BASE_URL=http://api.wandb.test python artifact_object_reference_test.py                                                               timothysweeney@Timothys-MacBook-Pro
import shutil

import os
import binascii
import base64
import time
from math import sin, cos, pi
import numpy as np
import sys
from bokeh.plotting import figure

PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    from wandb.sdk.interface import artifacts
else:
    from wandb.sdk_py27.interface import artifacts


WANDB_PROJECT_ENV = os.environ.get("WANDB_PROJECT")
if WANDB_PROJECT_ENV is None:
    WANDB_PROJECT = "test__" + str(round(time.time()) % 1000000)
else:
    WANDB_PROJECT = WANDB_PROJECT_ENV
os.environ["WANDB_PROJECT"] = WANDB_PROJECT

WANDB_SILENT_ENV = os.environ.get("WANDB_SILENT")
if WANDB_SILENT_ENV is None:
    WANDB_SILENT = "true"
else:
    WANDB_SILENT = WANDB_SILENT_ENV
os.environ["WANDB_SILENT"] = WANDB_SILENT

import wandb

columns = ["id", "class_id", "string", "bool", "int", "float", "Image", "Clouds", "HTML", "Video", "Bokeh"]

def _make_wandb_image(suffix=""):
    class_labels = {1: "tree", 2: "car", 3: "road"}
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "test{}.png".format(suffix))
    return wandb.Image(
        im_path,
        classes=wandb.Classes([
        {"id": 1, "name": "tree"},
        {"id": 2, "name": "car"},
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

def _make_point_cloud():
    # Generate a symetric pattern
    POINT_COUNT = 20000

    # Choose a random sample
    theta_chi = pi * np.random.rand(POINT_COUNT, 2)

    def gen_point(theta, chi, i):
        p = sin(theta) * 4.5 * sin(i + 1 / 2 * (i * i + 2)) + \
            cos(chi) * 7 * sin((2 * i - 4) / 2 * (i + 2))

        x = p * sin(chi) * cos(theta)
        y = p * sin(chi) * sin(theta)
        z = p * cos(chi)

        r = sin(theta) * 120 + 120
        g = sin(x) * 120 + 120
        b = cos(y) * 120 + 120

        return [x, y, z, r, g, b]

    def wave_pattern(i):
        return np.array([gen_point(theta, chi, i) for [theta, chi] in theta_chi])

    return wandb.Object3D(wave_pattern(0))

# static assets for comparisons
pc1 = _make_point_cloud()
pc2 = _make_point_cloud()
pc3 = _make_point_cloud()
pc4 = _make_point_cloud()

def _make_bokeh():
    x = [1, 2, 3, 4, 5]
    y = [6, 7, 2, 4, 5]
    p = figure(title="simple line example", x_axis_label='x', y_axis_label='y')
    p.line(x, y, legend_label="Temp.", line_width=2)

    return wandb.data_types.Bokeh(p)

b1 = _make_bokeh()
b2 = _make_bokeh()
b3 = _make_bokeh()
b4 = _make_bokeh()

def _make_html():
    return wandb.Html("<p>Embedded</p><iframe src='https://wandb.ai'></iframe>")

def _make_video():
    return wandb.Video(np.random.randint(0, high=255, size=(4, 1, 10, 10), dtype=np.uint8)) # 1 second video of 10x10 pixels

vid1 = _make_video()
vid2 = _make_video()
vid3 = _make_video()
vid4 = _make_video()

def _make_wandb_table():
    classes = wandb.Classes([
        {"id": 1, "name": "tree"},
        {"id": 2, "name": "car"},
        {"id": 3, "name": "road"},
    ])
    table = wandb.Table(
        columns=columns,
        data=[
            [1, 1, "string1", True, 1, 1.1, _make_wandb_image(), pc1, _make_html(), vid, b1],
            [2, 2, "string2", True, 1, 1.2, _make_wandb_image(), pc2, _make_html(), vid, b2],
            [3, 1, "string3", False, -0, -1.3, _make_wandb_image("2"), pc3, _make_html(), vid3, b3],
            [4, 3, "string4", False, -0, -1.4, _make_wandb_image("2"), pc4, _make_html(), vid4, b4],
        ],
    )
    table.cast("class_id", classes.get_type())
    return table

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
    if not os.path.exists(upstream_local_path):
        os.makedirs(upstream_local_path)
    with open(upstream_local_file_path, "w") as file:
        file.write(file_text)

    # Create an artifact with such file stored
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact(upstream_artifact_name, "database")
        artifact.add_file(upstream_local_file_path, upstream_artifact_file_path)
        run.log_artifact(artifact)

    # Create an middle artifact with such file referenced (notice no need to download)
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact(middle_artifact_name, "database")
        upstream_artifact = run.use_artifact(upstream_artifact_name + ":latest")
        artifact.add_reference(
            "wandb-artifact://{}/{}".format(_b64_to_hex_id(upstream_artifact.id),str(upstream_artifact_file_path)),
            middle_artifact_file_path,
        )
        run.log_artifact(artifact)

    # Create a downstream artifact that is referencing the middle's reference
    with wandb.init(project=WANDB_PROJECT) as run:
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
    with wandb.init(project=WANDB_PROJECT) as run:
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
    if not os.path.exists(upstream_local_path):
        os.makedirs(upstream_local_path)
    with open(upstream_local_file_path, "w") as file:
        file.write(file_text)

    # Create an artifact with such file stored
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact(upstream_artifact_name, "database")
        artifact.add_file(upstream_local_file_path, upstream_artifact_file_path)
        run.log_artifact(artifact)

    # Create an middle artifact with such file referenced (notice no need to download)
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact(middle_artifact_name, "database")
        upstream_artifact = run.use_artifact(upstream_artifact_name + ":latest")
        artifact.add_reference(
            upstream_artifact.get_path(upstream_artifact_file_path),
            middle_artifact_file_path,
        )
        run.log_artifact(artifact)

    # Create a downstream artifact that is referencing the middle's reference
    with wandb.init(project=WANDB_PROJECT) as run:
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
    with wandb.init(project=WANDB_PROJECT) as run:
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

    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact("A2", "database")
        image = _make_wandb_image()
        table = _make_wandb_table()
        artifact.add(image, "I1")
        artifact.add(table, "T1")
        run.log_artifact(artifact)

    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = run.use_artifact("A2:latest")
        actual_image = artifact.get("I1")
        assert actual_image == image

        actual_table = artifact.get("T1")
        assert actual_table.columns == columns
        assert actual_table.data[0][columns.index("Image")] == image
        assert actual_table.data[1][columns.index("Image")] == _make_wandb_image("2")
        assert actual_table == _make_wandb_table()


# # Artifact1.add(artifact2.get(MEDIA_NAME))
def test_adding_artifact_by_object():
    """This test validates that we can add wandb Media objects
    to an artifact by passing the object itself.
    """
    # Create an artifact with such file stored
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact("upstream_media", "database")
        artifact.add(_make_wandb_image(), "I1")
        run.log_artifact(artifact)

    # Create an middle artifact with such file referenced (notice no need to download)
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact("downstream_media", "database")
        upstream_artifact = run.use_artifact("upstream_media:latest")
        artifact.add(upstream_artifact.get("I1"), "T2")
        run.log_artifact(artifact)

    if os.path.isdir("artifacts"):
        shutil.rmtree("artifacts")

    with wandb.init(project=WANDB_PROJECT) as run:
        downstream_artifact = run.use_artifact("downstream_media:latest")
        downstream_path = downstream_artifact.download()
        # assert os.path.islink(os.path.join(downstream_path, "T2.image-file.json"))
        assert downstream_artifact.get("T2") == _make_wandb_image()

def _cleanup():
    artifacts.get_artifacts_cache()._artifacts_by_id = {}
    if os.path.isdir("wandb"):
        shutil.rmtree("wandb")
    if os.path.isdir("artifacts"):
        shutil.rmtree("artifacts")
    if os.path.isdir("upstream"):
        shutil.rmtree("upstream")


def test_image_reference_artifact():
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact("image_data", "data")
        image = _make_wandb_image()
        artifact.add(image, "image")
        run.log_artifact(artifact)

    with wandb.init(project=WANDB_PROJECT) as run:
        artifact_1 = run.use_artifact("image_data:latest")
        artifact = wandb.Artifact("reference_data", "data")
        artifact.add(artifact_1.get("image"), "image_2")
        run.log_artifact(artifact)

    _cleanup()
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact_2 = run.use_artifact("reference_data:latest")
        artifact_2.download()
        # assert os.path.islink(os.path.join(artifact_2._default_root(), "image_2.image-file.json"))


def test_nested_reference_artifact():
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact("image_data", "data")
        image = _make_wandb_image()
        artifact.add(image, "image")
        run.log_artifact(artifact)

    with wandb.init(project=WANDB_PROJECT) as run:
        artifact_1 = run.use_artifact("image_data:latest")
        artifact = wandb.Artifact("reference_data", "data")
        table = wandb.Table(["image"], [[artifact_1.get("image")]])
        artifact.add(table, "table_2")
        run.log_artifact(artifact)

    with wandb.init(project=WANDB_PROJECT) as run:
        artifact_3 = run.use_artifact("reference_data:latest")
        table_2 = artifact_3.get("table_2")
        # assert os.path.islink(os.path.join(artifact_3._default_root(), "media", "images", "test.png"))
        assert table == table_2
        artifact_3.download()

    


def test_table_slice_reference_artifact():
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact("table_data", "data")
        table = _make_wandb_table()
        artifact.add(table, "table")
        run.log_artifact(artifact)

    with wandb.init(project=WANDB_PROJECT) as run:
        artifact_1 = run.use_artifact("table_data:latest")
        t1 = artifact_1.get("table")
        artifact = wandb.Artifact("intermediate_data", "data")
        i1 = wandb.Table(t1.columns, t1.data[:1])
        i2 = wandb.Table(t1.columns, t1.data[1:])
        artifact.add(i1, "table1")
        artifact.add(i2, "table2")
        run.log_artifact(artifact)

    with wandb.init(project=WANDB_PROJECT) as run:
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
    with wandb.init(project=WANDB_PROJECT) as run:
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
    with wandb.init(project=WANDB_PROJECT) as run:
        orig_artifact = wandb.Artifact("orig_artifact", "database")
        orig_artifact.add(obj, "obj")
        run.log_artifact(orig_artifact)

    _cleanup()
    with wandb.init(project=WANDB_PROJECT) as run:
        orig_artifact_ref = run.use_artifact("orig_artifact:latest")
        orig_dir = orig_artifact_ref._default_root()
        obj1 = orig_artifact_ref.get("obj")

    assert obj1 == obj
    target_path = os.path.join(orig_dir, "obj." + type(obj).artifact_type + ".json")
    assert os.path.isfile(target_path)

    with wandb.init(project=WANDB_PROJECT) as run:
        orig_artifact_ref = run.use_artifact("orig_artifact:latest")
        mid_artifact = wandb.Artifact("mid_artifact", "database")
        mid_obj = orig_artifact_ref.get("obj")
        mid_artifact.add(mid_obj, "obj2")
        run.log_artifact(mid_artifact)

    _cleanup()
    with wandb.init(project=WANDB_PROJECT) as run:
        mid_artifact_ref = run.use_artifact("mid_artifact:latest")
        mid_dir = mid_artifact_ref._default_root()
        obj2 = mid_artifact_ref.get("obj2")

    assert obj2 == obj
    # name = "obj2." + type(obj).artifact_type + ".json"
    # start_path = os.path.join(mid_dir, name)
    # mid_artifact_ref.get_path(name).download()
    # assert os.path.islink(start_path)
    # assert os.path.abspath(os.readlink(start_path)) == os.path.abspath(target_path)

    with wandb.init(project=WANDB_PROJECT) as run:
        mid_artifact_ref = run.use_artifact("mid_artifact:latest")
        down_artifact = wandb.Artifact("down_artifact", "database")
        down_obj = mid_artifact_ref.get("obj2")
        down_artifact.add(down_obj, "obj3")
        run.log_artifact(down_artifact)

    _cleanup()
    with wandb.init(project=WANDB_PROJECT) as run:
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


def test_point_cloud_refs():
    assert_media_obj_referential_equality(_make_point_cloud())

def test_bokeh_refs():
    assert_media_obj_referential_equality(_make_bokeh())

def test_html_refs():
    assert_media_obj_referential_equality(_make_html())

def test_video_refs():
    assert_media_obj_referential_equality(_make_video())


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

    with wandb.init(project=WANDB_PROJECT) as run:
        orig_artifact = wandb.Artifact("art1", "database")
        orig_artifact.add(src_jt_1, "src_jt_1")
        run.log_artifact(orig_artifact)

    with wandb.init(project=WANDB_PROJECT) as run:
        art1 = run.use_artifact("art1:latest")
        src_jt_1 = art1.get("src_jt_1")
        src_jt_2 = wandb.JoinedTable(src_jt_1._table1, src_jt_1._table2, "id")
        art2 = wandb.Artifact("art2", "database")
        art2.add(src_jt_2, "src_jt_2")
        run.log_artifact(art2)

    _cleanup()
    with wandb.init(project=WANDB_PROJECT) as run:
        art2 = run.use_artifact("art2:latest")
        src_jt_2 = art2.get("src_jt_2")
        assert src_jt_1 == src_jt_2

def test_joined_table_add_by_path():
    src_image_1 = _make_wandb_image()
    src_image_2 = _make_wandb_image()
    src_image_3 = _make_wandb_image()
    src_image_4 = _make_wandb_image()
    src_table_1 = wandb.Table(["id", "image"], [[1, src_image_1], [2, src_image_2]])
    src_table_2 = wandb.Table(["id", "image"], [[1, src_image_3], [2, src_image_4]])
    with wandb.init(project=WANDB_PROJECT) as run:
        tables = wandb.Artifact("tables", "database")
        tables.add(src_table_1, "src_table_1")
        tables.add(src_table_2, "src_table_2")

        # Should be able to add by name directly
        jt = wandb.JoinedTable("src_table_1.table.json", "src_table_2.table.json", "id")
        tables.add(jt, "jt")

        # Make sure it errors when you are not referencing the correct table names
        jt_bad = wandb.JoinedTable("bad_table_name.table.json", "bad_table_name.table.json", "id")
        got_err = False
        try:
            tables.add(jt_bad, "jt_bad")
        except ValueError as err:
            got_err = True
        assert got_err

        run.log_artifact(tables)

    _cleanup()
    with wandb.init(project=WANDB_PROJECT) as run:
        tables_2 = wandb.Artifact("tables_2", "database")
        upstream = run.use_artifact("tables:latest")
        
        # Able to add by reference
        jt = wandb.JoinedTable(upstream.get_path("src_table_1"), upstream.get_path("src_table_2"), "id")
        tables_2.add(jt, "jt")
        run.log_artifact(tables_2)

    _cleanup()
    with wandb.init(project=WANDB_PROJECT) as run:
        tables_2 = run.use_artifact("tables_2:latest")
        jt_2 = tables_2.get("jt")
        assert wandb.JoinedTable(upstream.get("src_table_1"), upstream.get("src_table_2"), "id") == jt_2

def test_image_reference_with_preferred_path():
    orig_im_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "assets", "test.png")
    orig_im_path_2 = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "assets", "test2.png")
    desired_artifact_path = "images/sample.png"
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact("artifact_1", type="test_artifact")
        # manually add the image to a desired path
        artifact.add_file(orig_im_path, desired_artifact_path)
        # create an image that uses this image (it should be smart enough not to add the image twice)
        image = wandb.Image(orig_im_path)
        image_2 = wandb.Image(orig_im_path_2) # this one does not have the path preadded
        # add the image to the table
        table = wandb.Table(["image"], data=[[image],[image_2]])
        # add the table to the artifact
        artifact.add(table, "table")
        run.log_artifact(artifact)
    
    _cleanup()
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact_1 = run.use_artifact("artifact_1:latest")
        original_table = artifact_1.get("table")

        artifact = wandb.Artifact("artifact_2", type="test_artifact")
        
        # add the image by reference
        image = wandb.Image(original_table.data[0][0])
        image_2 = wandb.Image(original_table.data[1][0])
        # add the image to the table
        table = wandb.Table(["image"], data=[[image],[image_2]])
        # add the table to the artifact
        artifact.add(table, "table")
        run.log_artifact(artifact)

    _cleanup()
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact_2 = run.use_artifact("artifact_2:latest")
        artifact_2.download()
    
    # This test just checks that all this logic does not fail

if __name__ == "__main__":
    _cleanup()
    test_fns = [
        test_artifact_add_reference_via_url,
        test_add_reference_via_artifact_entry,
        test_adding_artifact_by_object,
        test_get_artifact_obj_by_name,
        test_image_reference_artifact,
        test_nested_reference_artifact,
        test_table_slice_reference_artifact,
        test_image_refs,
        test_point_cloud_refs,
        test_bokeh_refs,
        test_html_refs,
        test_video_refs,
        test_table_refs,
        test_joined_table_refs,
        test_joined_table_referential,
        test_joined_table_add_by_path,
        test_image_reference_with_preferred_path,
    ]
    for ndx, test_fn in enumerate(test_fns):
        try:
            test_fn()
            _cleanup()
            print("{}/{} Complete".format(ndx+1, len(test_fns)))
        except Exception as exception:
            print("error on function {}".format(test_fn.__name__))
            raise exception
        finally:
            _cleanup()

    if WANDB_PROJECT_ENV is not None:
        os.environ["WANDB_PROJECT"] = WANDB_PROJECT_ENV

    if WANDB_SILENT_ENV is not None:
        os.environ["WANDB_SILENT"] = WANDB_SILENT_ENV