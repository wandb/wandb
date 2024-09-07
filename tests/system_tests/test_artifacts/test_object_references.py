from __future__ import annotations

import base64
import binascii
import shutil
import time
from collections.abc import Callable
from contextlib import suppress
from math import cos, pi, sin
from pathlib import Path

import boto3
import botocore
import google.cloud.storage
import numpy as np
import pytest
from bokeh.plotting import figure
from typing_extensions import Final

import wandb
from wandb import Html, Object3D
from wandb.data_types import Bokeh
from wandb.sdk.artifacts.storage_handlers.gcs_handler import GCSHandler
from wandb.sdk.artifacts.storage_handlers.s3_handler import S3Handler
from wandb.sdk.data_types.base_types.wb_value import WBValue

COLUMNS: Final[list[str]] = [
    "id",
    "class_id",
    "string",
    "bool",
    "int",
    "float",
    "Image",
    "Clouds",
    "HTML",
    "Video",
    "Bokeh",
    "Audio",
    "np_data",
]

CLASS_LABELS: Final[dict[int, str]] = {
    1: "tree",
    2: "car",
    3: "road",
}

WANDB_CLASSES: Final[wandb.Classes] = wandb.Classes(
    [{"id": idx, "name": lbl} for idx, lbl in CLASS_LABELS.items()]
)


@pytest.fixture(scope="module")
def tmp_assets_dir(tmp_path_factory) -> Path:
    """A temporary directory with copies of test assets, for extra safety."""
    orig_dir = Path(__file__).resolve().parent.parent.parent / "assets"

    tmp_dir = tmp_path_factory.mktemp("assets")

    shutil.copy(src=orig_dir / "test.png", dst=tmp_dir)
    shutil.copy(src=orig_dir / "test2.png", dst=tmp_dir)

    yield tmp_dir


@pytest.fixture(scope="module")
def make_wandb_image(tmp_assets_dir) -> Callable[[str], wandb.Image]:
    """Factory fixture for generating test `wandb.Image` objects."""

    def _make_wandb_image(name: str) -> wandb.Image:
        # assets_path = Path(__file__).resolve().parent.parent.parent / "assets"

        img_path = str(tmp_assets_dir / f"{name}.png")

        position = {"minX": 0.1, "maxX": 0.2, "minY": 0.3, "maxY": 0.4}
        box_caption = "minMax(pixel)"
        scores = {"acc": 0.1, "loss": 1.2}

        box1 = {
            "position": position,
            "class_id": 1,
            "box_caption": box_caption,
            "scores": scores,
        }
        box2 = {
            "position": position,
            "class_id": 2,
            "box_caption": box_caption,
            "scores": scores,
        }
        return wandb.Image(
            img_path,
            classes=WANDB_CLASSES,
            boxes={
                "predictions": {
                    "box_data": [box1, box2],
                    "class_labels": CLASS_LABELS,
                },
                "ground_truth": {
                    "box_data": [box1, box2],
                    "class_labels": CLASS_LABELS,
                },
            },
            masks={
                "predictions": {
                    "mask_data": np.random.randint(0, 4, size=(30, 30)),
                    "class_labels": CLASS_LABELS,
                },
                "ground_truth": {
                    "path": img_path,
                    "class_labels": CLASS_LABELS,
                },
            },
        )

    return _make_wandb_image


@pytest.fixture(scope="module")
def wandb_image_1(make_wandb_image) -> wandb.Image:
    return make_wandb_image("test")


@pytest.fixture(scope="module")
def wandb_image_2(make_wandb_image) -> wandb.Image:
    return make_wandb_image("test2")


@pytest.fixture(scope="module")
def make_point_cloud() -> Callable[[], Object3D]:
    def _make_point_cloud() -> Object3D:
        # Generate a symmetric pattern
        point_count = 20000

        # Choose a random sample
        theta_chi = pi * np.random.rand(point_count, 2)

        def gen_point(theta: float, chi: float, i: int):
            p = sin(theta) * 4.5 * sin(i + 0.5 * (i**2 + 2)) + cos(chi) * 7 * sin(
                0.5 * (2 * i - 4) * (i + 2)
            )

            x = p * sin(chi) * cos(theta)
            y = p * sin(chi) * sin(theta)
            z = p * cos(chi)

            r = sin(theta) * 120 + 120
            g = sin(x) * 120 + 120
            b = cos(y) * 120 + 120

            return [x, y, z, r, g, b]

        def wave_pattern(i: int):
            return np.array([gen_point(theta, chi, i) for [theta, chi] in theta_chi])

        return Object3D(wave_pattern(0))

    return _make_point_cloud


@pytest.fixture
def wandb_point_cloud(make_point_cloud) -> Object3D:
    return make_point_cloud()


# static assets for comparisons
@pytest.fixture(scope="module")
def point_clouds(
    make_point_cloud,
) -> tuple[Object3D, Object3D, Object3D, Object3D]:
    return (
        make_point_cloud(),
        make_point_cloud(),
        make_point_cloud(),
        make_point_cloud(),
    )


@pytest.fixture(scope="module")
def make_bokeh() -> Callable[[], Bokeh]:
    def _make_bokeh():
        x = [1, 2, 3, 4, 5]
        y = [6, 7, 2, 4, 5]
        p = figure(title="simple line example", x_axis_label="x", y_axis_label="y")
        p.line(x, y, legend_label="Temp.", line_width=2)

        return Bokeh(p)

    return _make_bokeh


@pytest.fixture(scope="module")
def bokeh_objs(make_bokeh) -> tuple[Bokeh, Bokeh, Bokeh, Bokeh]:
    return make_bokeh(), make_bokeh(), make_bokeh(), make_bokeh()


@pytest.fixture(scope="module")
def make_html() -> Callable[[], Html]:
    """Factory fixture for generating test `wandb.Html` objects."""

    def _make_html() -> Html:
        return Html("<p>Embedded</p><iframe src='https://wandb.ai'></iframe>")

    return _make_html


@pytest.fixture(scope="module")
def wandb_html(make_html) -> Html:
    return make_html()


@pytest.fixture(scope="module")
def make_video() -> Callable[[], wandb.Video]:
    """Factory fixture for generating test `wandb.Video` objects."""

    def _make_video() -> wandb.Video:
        # time, channel, height, width
        return wandb.Video(
            np.random.randint(0, high=255, size=(4, 3, 10, 10), dtype=np.uint8)
        )

    return _make_video


@pytest.fixture(scope="module")
def vid_objs(make_video) -> tuple[wandb.Video, wandb.Video, wandb.Video, wandb.Video]:
    return make_video(), make_video(), make_video(), make_video()


@pytest.fixture(scope="module")
def aud_sample() -> wandb.Audio:
    freq = 440
    caption = "four forty"

    sample_rate = 44_100
    duration = 1

    data = np.sin(2 * np.pi * np.arange(sample_rate * duration) * freq / sample_rate)
    return wandb.Audio(data, sample_rate, caption)


@pytest.fixture(scope="module")
def aud_ref_https() -> wandb.Audio:
    return wandb.Audio(
        "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav",
        caption="star wars https",
    )


@pytest.fixture(scope="module")
def aud_ref_s3() -> wandb.Audio:
    return wandb.Audio(
        "s3://wandb-artifacts-refs-public-test/StarWars3.wav",
        caption="star wars s3",
    )


@pytest.fixture(scope="module")
def aud_ref_gs() -> wandb.Audio:
    return wandb.Audio(
        "gs://wandb-artifact-refs-public-test/StarWars3.wav",
        caption="star wars gs",
    )


@pytest.fixture(scope="module")
def np_data() -> np.ndarray:
    return np.random.randint(255, size=(4, 16, 16, 3))


@pytest.fixture(scope="module")
def make_wandb_table(
    wandb_image_1,
    wandb_image_2,
    wandb_html,
    point_clouds,
    vid_objs,
    bokeh_objs,
    np_data,
    aud_sample,
    aud_ref_https,
    aud_ref_s3,
    aud_ref_gs,
) -> Callable[[], wandb.Table]:
    """Factory fixture for generating test `wandb.Table` objects."""

    def _make_wandb_table():
        table = wandb.Table(
            columns=[c for c in COLUMNS[:-1]],
            data=[
                [
                    1,
                    1,
                    "string1",
                    True,
                    1,
                    1.1,
                    wandb_image_1,
                    point_clouds[0],
                    wandb_html,
                    vid_objs[0],
                    bokeh_objs[0],
                    aud_sample,
                ],
                [
                    2,
                    2,
                    "string2",
                    True,
                    1,
                    1.2,
                    wandb_image_1,
                    point_clouds[1],
                    wandb_html,
                    vid_objs[1],
                    bokeh_objs[1],
                    aud_ref_https,
                ],
                [
                    3,
                    1,
                    "string3",
                    False,
                    -0,
                    -1.3,
                    wandb_image_2,
                    point_clouds[2],
                    wandb_html,
                    vid_objs[2],
                    bokeh_objs[2],
                    aud_ref_s3,
                ],
                [
                    4,
                    3,
                    "string4",
                    False,
                    -0,
                    -1.4,
                    wandb_image_2,
                    point_clouds[3],
                    wandb_html,
                    vid_objs[3],
                    bokeh_objs[3],
                    aud_ref_gs,
                ],
            ],
        )
        table.cast("class_id", WANDB_CLASSES.get_type())
        table.add_column(COLUMNS[-1], np_data)
        return table

    return _make_wandb_table


@pytest.fixture
def wandb_image(make_wandb_image) -> wandb.Image:
    return make_wandb_image("test")


@pytest.fixture
def wandb_table(make_wandb_table) -> wandb.Table:
    return make_wandb_table()


@pytest.fixture
def wandb_joinedtable(make_wandb_table) -> wandb.JoinedTable:
    return wandb.JoinedTable(make_wandb_table(), make_wandb_table(), join_key="id")


def _b64_to_hex_id(id_string: str) -> str:
    return binascii.hexlify(base64.standard_b64decode(str(id_string))).decode("utf-8")


# Artifact1.add_reference(artifact_URL) => recursive reference
def test_artifact_add_reference_via_url(wandb_init, tmp_path, cleanup):
    """Test adding a reference to an artifact via a URL.

    This test creates three artifacts. The middle artifact references the first
    artifact's file, and the last artifact references the middle artifact's reference.
    The end result of downloading the last artifact in a fresh, forth run, should be
    that all 3 artifacts are downloaded and that the file in the last artifact is
    actually a symlink to the first artifact's file.
    """
    upstream_artifact_name = "upstream_artifact"
    middle_artifact_name = "middle_artifact"
    downstream_artifact_name = "downstream_artifact"

    upstream_local_path = tmp_path / "upstream/local/path"
    upstream_artifact_path = tmp_path / "upstream/artifact/path"
    middle_artifact_path = tmp_path / "middle/artifact/path"
    downstream_artifact_path = tmp_path / "downstream/artifact/path"

    upstream_local_file_path = upstream_local_path / "file.txt"
    upstream_artifact_file_path = upstream_artifact_path / "file.txt"
    middle_artifact_file_path = middle_artifact_path / "file.txt"
    downstream_artifact_file_path = downstream_artifact_path / "file.txt"

    file_text = "Luke, I am your Father!!!!!"
    # Create a super important file
    upstream_local_path.mkdir(parents=True, exist_ok=True)
    upstream_local_file_path.write_text(file_text)

    # Create an artifact with such file stored
    with wandb_init() as run:
        artifact = wandb.Artifact(upstream_artifact_name, "database")
        artifact.add_file(
            str(upstream_local_file_path), str(upstream_artifact_file_path)
        )
        run.log_artifact(artifact)

    # Create an middle artifact with such file referenced (notice no need to download)
    with wandb_init() as run:
        artifact = wandb.Artifact(middle_artifact_name, "database")
        upstream_artifact = run.use_artifact(f"{upstream_artifact_name}:latest")
        artifact.add_reference(
            f"wandb-artifact://{_b64_to_hex_id(upstream_artifact.id)}/{upstream_artifact_file_path!s}",
            middle_artifact_file_path,
        )
        run.log_artifact(artifact)

    # Create a downstream artifact that is referencing the middle's reference
    with wandb_init() as run:
        artifact = wandb.Artifact(downstream_artifact_name, "database")
        middle_artifact = run.use_artifact(f"{middle_artifact_name!s}:latest")
        artifact.add_reference(
            f"wandb-artifact://{_b64_to_hex_id(middle_artifact.id)}/{middle_artifact_file_path!s}",
            downstream_artifact_file_path,
        )
        run.log_artifact(artifact)

    # Remove the directories for good measure
    with suppress(OSError):
        shutil.rmtree("upstream")
    with suppress(OSError):
        shutil.rmtree("artifacts")

    # Finally, use the artifact (download it) and enforce that the file is where we want it!
    with wandb_init() as run:
        downstream_artifact = run.use_artifact(f"{downstream_artifact_name!s}:latest")
        downstream_path = downstream_artifact.download()
        assert (
            Path(downstream_path) / downstream_artifact_file_path
        ).read_text() == file_text


# # Artifact1.add_reference(artifact2.get_entry(file_name))
def test_add_reference_via_artifact_entry(wandb_init, tmp_path, cleanup):
    """Test adding a reference to an artifact via an ArtifactEntry.

    This test is the same as test_artifact_add_reference_via_url, but rather than
    passing the direct URL, we pass an Artifact entry, which will automatically resolve
    to the correct URL.
    """
    upstream_artifact_name = "upstream_artifact"
    middle_artifact_name = "middle_artifact"
    downstream_artifact_name = "downstream_artifact"

    upstream_local_dir = tmp_path / "upstream/local/path"
    upstream_artifact_dir = tmp_path / "upstream/artifact/path"
    middle_artifact_dir = tmp_path / "middle/artifact/path"
    downstream_artifact_dir = tmp_path / "downstream/artifact/path"

    upstream_local_file_path = upstream_local_dir / "file.txt"
    upstream_artifact_file_path = upstream_artifact_dir / "file.txt"
    middle_artifact_file_path = middle_artifact_dir / "file.txt"
    downstream_artifact_file_path = downstream_artifact_dir / "file.txt"

    file_text = "Luke, I am your Father!!!!!"
    # Create a super important file
    upstream_local_dir.mkdir(parents=True, exist_ok=True)
    upstream_local_file_path.write_text(file_text)

    # Create an artifact with such file stored
    with wandb_init() as run:
        artifact = wandb.Artifact(upstream_artifact_name, "database")
        artifact.add_file(
            str(upstream_local_file_path), str(upstream_artifact_file_path)
        )
        run.log_artifact(artifact)

    # Create an middle artifact with such file referenced (notice no need to download)
    with wandb_init() as run:
        artifact = wandb.Artifact(middle_artifact_name, "database")
        upstream_artifact = run.use_artifact(f"{upstream_artifact_name!s}:latest")
        artifact.add_reference(
            upstream_artifact.get_entry(upstream_artifact_file_path),
            middle_artifact_file_path,
        )
        run.log_artifact(artifact)

    # Create a downstream artifact that is referencing the middle's reference
    with wandb_init() as run:
        artifact = wandb.Artifact(downstream_artifact_name, "database")
        middle_artifact = run.use_artifact(f"{middle_artifact_name}:latest")
        artifact.add_reference(
            middle_artifact.get_entry(middle_artifact_file_path),
            downstream_artifact_file_path,
        )
        run.log_artifact(artifact)

    # Remove the directories for good measure
    with suppress(OSError):
        shutil.rmtree("upstream")
    with suppress(OSError):
        shutil.rmtree("artifacts")

    # Finally, use the artifact (download it) and enforce that the file is where we want it!
    with wandb_init() as run:
        downstream_artifact = run.use_artifact(f"{downstream_artifact_name!s}:latest")
        downstream_path = downstream_artifact.download()
        _ = downstream_artifact.download()  # should not fail on second download.

        assert (
            Path(downstream_path) / downstream_artifact_file_path
        ).read_text() == file_text


# # Artifact1.get(MEDIA_NAME) => media obj
def test_get_artifact_obj_by_name(
    wandb_init,
    cleanup,
    anon_cloud_handlers,
    make_wandb_image,
    make_wandb_table,
):
    """Test the ability to instantiate a wandb Media object from the name of the object.

    This is the logical inverse of Artifact.add(name).
    """
    # TODO: test more robustly for every Media type, nested objects (eg. Table -> Image), and references.
    with wandb_init() as run:
        artifact = wandb.Artifact("A2", "database")
        image = make_wandb_image("test")
        table = make_wandb_table()
        artifact.add(image, "I1")
        artifact.add(table, "T1")
        run.log_artifact(artifact)

    with wandb_init() as run:
        artifact = run.use_artifact("A2:latest")
        actual_image = artifact.get("I1")
        assert actual_image == image

        actual_table = artifact.get("T1")
        assert isinstance(actual_table, wandb.Table)
        assert actual_table.columns == COLUMNS
        assert actual_table.data[0][COLUMNS.index("Image")] == image
        assert actual_table.data[1][COLUMNS.index("Image")] == make_wandb_image("test2")
        actual_table._eq_debug(make_wandb_table(), True)
        assert actual_table == make_wandb_table()


# # Artifact1.add(artifact2.get(MEDIA_NAME))
def test_adding_artifact_by_object(wandb_init, cleanup, make_wandb_image):
    """Test adding wandb Media objects to an artifact by passing the object itself."""
    # Create an artifact with such file stored
    with wandb_init() as run:
        artifact = wandb.Artifact("upstream_media", "database")
        artifact.add(make_wandb_image("test"), "I1")
        run.log_artifact(artifact)

    # Create an middle artifact with such file referenced (notice no need to download)
    with wandb_init() as run:
        artifact = wandb.Artifact("downstream_media", "database")
        upstream_artifact = run.use_artifact("upstream_media:latest")
        artifact.add(upstream_artifact.get("I1"), "T2")
        run.log_artifact(artifact)

    with suppress(OSError):
        shutil.rmtree("artifacts")

    with wandb_init() as run:
        downstream_artifact = run.use_artifact("downstream_media:latest")
        downstream_path = downstream_artifact.download()  # noqa: F841
        assert downstream_artifact.get("T2") == make_wandb_image("test")


def test_image_reference_artifact(wandb_init, cleanup, wandb_image):
    with wandb_init() as run:
        artifact = wandb.Artifact("image_data", "data")
        artifact.add(wandb_image, "image")
        run.log_artifact(artifact)

    with wandb_init() as run:
        artifact_1 = run.use_artifact("image_data:latest")
        artifact = wandb.Artifact("reference_data", "data")
        artifact.add(artifact_1.get("image"), "image_2")
        run.log_artifact(artifact)

    _cleanup()
    with wandb_init() as run:
        artifact_2 = run.use_artifact("reference_data:latest")
        artifact_2.download()


def test_nested_reference_artifact(wandb_init, cleanup, wandb_image):
    with wandb_init() as run:
        artifact = wandb.Artifact("image_data", "data")
        artifact.add(wandb_image, "image")
        run.log_artifact(artifact)

    with wandb_init() as run:
        artifact_1 = run.use_artifact("image_data:latest")
        artifact = wandb.Artifact("reference_data", "data")
        table = wandb.Table(["image"], [[artifact_1.get("image")]])
        artifact.add(table, "table_2")
        run.log_artifact(artifact)

    with wandb_init() as run:
        artifact_3 = run.use_artifact("reference_data:latest")
        table_2 = artifact_3.get("table_2")
        table._eq_debug(table_2, True)
        assert table == table_2
        artifact_3.download()


def test_table_slice_reference_artifact(
    wandb_init,
    cleanup,
    anon_cloud_handlers,
    wandb_table,
):
    with wandb_init() as run:
        artifact = wandb.Artifact("table_data", "data")
        artifact.add(wandb_table, "table")
        run.log_artifact(artifact)

    with wandb_init() as run:
        artifact_1 = run.use_artifact("table_data:latest")
        t1 = artifact_1.get("table")
        artifact = wandb.Artifact("intermediate_data", "data")
        i1 = wandb.Table(t1.columns, t1.data[:1])
        i2 = wandb.Table(t1.columns, t1.data[1:])
        artifact.add(i1, "table1")
        artifact.add(i2, "table2")
        run.log_artifact(artifact)

    with wandb_init() as run:
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
    with wandb_init() as run:
        artifact_3 = run.use_artifact("reference_data:latest")
        table1 = artifact_3.get("table1")
        table2 = artifact_3.get("table2")

    assert not Path(artifact_2._default_root()).is_dir()

    def assert_eq_data(d1, d2):
        assert len(d1) == len(d2)
        for ndx in range(len(d1)):
            assert len(d1[ndx]) == len(d2[ndx])
            for i in range(len(d1[ndx])):
                eq = d1[ndx][i] == d2[ndx][i]
                if isinstance(eq, list) or isinstance(eq, np.ndarray):
                    assert np.all(eq)
                else:
                    assert eq

    assert_eq_data(t1.data[:1], table1.data)
    assert_eq_data(t1.data[1:], table2.data)


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
def assert_media_obj_referential_equality(wandb_init, obj: WBValue):
    orig_entry_name = "obj"
    with wandb_init() as run1:
        orig_artifact = wandb.Artifact("orig_artifact", "database")
        orig_artifact.add(obj, orig_entry_name)
        run1.log_artifact(orig_artifact)

    with wandb_init() as run2:
        orig_artifact_ref = run2.use_artifact(f"{orig_artifact.name}:latest")
        orig_dir = orig_artifact_ref._default_root()
        obj1 = orig_artifact_ref.get(orig_entry_name)

    if hasattr(obj, "_eq_debug"):
        obj._eq_debug(obj1, True)

    assert obj1 == obj

    target_filename = obj.with_suffix(name=orig_entry_name, filetype="json")
    target_path = Path(orig_dir) / target_filename
    assert target_path.is_file()

    mid_entry_name = "obj2"
    with wandb_init() as run3:
        orig_artifact_ref = run3.use_artifact(f"{orig_artifact.name}:latest")
        mid_obj = orig_artifact_ref.get(orig_entry_name)

        mid_artifact = wandb.Artifact("mid_artifact", "database")
        mid_artifact.add(mid_obj, mid_entry_name)
        run3.log_artifact(mid_artifact)

    with wandb_init() as run4:
        mid_artifact_ref = run4.use_artifact(f"{mid_artifact.name}:latest")
        mid_dir = mid_artifact_ref._default_root()
        obj2 = mid_artifact_ref.get(mid_entry_name)

    assert not Path(mid_dir).is_dir()

    if hasattr(obj, "_eq_debug"):
        obj._eq_debug(obj2, True)

    assert obj2 == obj

    last_obj_name = "obj3"
    with wandb_init() as run5:
        mid_artifact_ref = run5.use_artifact(f"{mid_artifact.name}:latest")
        last_obj = mid_artifact_ref.get(mid_entry_name)

        last_artifact = wandb.Artifact("last_artifact", "database")
        last_artifact.add(last_obj, last_obj_name)
        run5.log_artifact(last_artifact)

    with wandb_init() as run6:
        last_artifact_ref = run6.use_artifact(f"{last_artifact.name}:latest")
        last_dir = last_artifact_ref._default_root()  # noqa: F841
        obj3 = last_artifact_ref.get(last_obj_name)

    assert not Path(last_dir).is_dir()

    if hasattr(obj, "_eq_debug"):
        obj._eq_debug(obj3, True)

    assert obj3 == obj


def test_table_refs(
    wandb_init,
    cleanup,
    anon_cloud_handlers,
    wandb_table,
):
    assert_media_obj_referential_equality(wandb_init, wandb_table)


def test_image_refs(wandb_init, cleanup, wandb_image):
    assert_media_obj_referential_equality(wandb_init, wandb_image)


def test_point_cloud_refs(wandb_init, cleanup, wandb_point_cloud):
    assert_media_obj_referential_equality(wandb_init, wandb_point_cloud)


def test_bokeh_refs(wandb_init, cleanup, make_bokeh):
    assert_media_obj_referential_equality(wandb_init, make_bokeh())


def test_html_refs(wandb_init, cleanup, wandb_html):
    assert_media_obj_referential_equality(wandb_init, wandb_html)


def test_video_refs(wandb_init, cleanup, make_video):
    assert_media_obj_referential_equality(wandb_init, make_video())


def test_joined_table_refs(
    wandb_init,
    cleanup,
    anon_cloud_handlers,
    wandb_joinedtable,
):
    assert_media_obj_referential_equality(wandb_init, wandb_joinedtable)


@pytest.mark.timeout(60)
def test_audio_ref_https(
    wandb_init,
    cleanup,
    anon_cloud_handlers,
    aud_ref_https,
):
    assert_media_obj_referential_equality(wandb_init, aud_ref_https)


@pytest.mark.timeout(60)
def test_audio_ref_s3(
    wandb_init,
    cleanup,
    anon_cloud_handlers,
    aud_ref_s3,
):
    assert_media_obj_referential_equality(wandb_init, aud_ref_s3)


@pytest.mark.timeout(60)
def test_audio_ref_gs(
    wandb_init,
    cleanup,
    anon_cloud_handlers,
    aud_ref_gs,
):
    assert_media_obj_referential_equality(wandb_init, aud_ref_gs)


def test_joined_table_referential(wandb_init, cleanup, make_wandb_image):
    columns = ["id", "image"]
    src_table_1 = wandb.Table(
        columns=columns,
        data=[
            [1, make_wandb_image("test")],
            [2, make_wandb_image("test")],
        ],
    )
    src_table_2 = wandb.Table(
        columns=columns,
        data=[
            [1, make_wandb_image("test")],
            [2, make_wandb_image("test")],
        ],
    )
    src_jt_1 = wandb.JoinedTable(src_table_1, src_table_2, "id")

    with wandb_init() as run:
        orig_artifact = wandb.Artifact("art1", "database")
        orig_artifact.add(src_jt_1, "src_jt_1")
        run.log_artifact(orig_artifact)

    with wandb_init() as run:
        art1 = run.use_artifact("art1:latest")
        src_jt_1 = art1.get("src_jt_1")
        src_jt_2 = wandb.JoinedTable(src_jt_1._table1, src_jt_1._table2, "id")
        art2 = wandb.Artifact("art2", "database")
        art2.add(src_jt_2, "src_jt_2")
        run.log_artifact(art2)

    _cleanup()
    with wandb_init() as run:
        art2 = run.use_artifact("art2:latest")
        src_jt_2 = art2.get("src_jt_2")
        src_jt_1._eq_debug(src_jt_2, True)
        assert src_jt_1 == src_jt_2


def test_joined_table_add_by_path(wandb_init, cleanup, wandb_image_1):
    src_table_1 = wandb.Table(
        columns=["id", "image"],
        data=[
            [1, wandb_image_1],
            [2, wandb_image_1],
        ],
    )
    src_table_2 = wandb.Table(
        columns=["id", "image"],
        data=[
            [1, wandb_image_1],
            [2, wandb_image_1],
        ],
    )
    with wandb_init() as run:
        tables = wandb.Artifact("tables", "database")
        tables.add(src_table_1, "src_table_1")
        tables.add(src_table_2, "src_table_2")

        # Should be able to add by name directly
        jt = wandb.JoinedTable(
            "src_table_1.table.json",
            "src_table_2.table.json",
            join_key="id",
        )
        tables.add(jt, "jt")

        # Make sure it errors when you are not referencing the correct table names
        jt_bad = wandb.JoinedTable(
            "bad_table_name.table.json",
            "bad_table_name.table.json",
            join_key="id",
        )

        with pytest.raises(ValueError):
            tables.add(jt_bad, "jt_bad")

        run.log_artifact(tables)

    _cleanup()
    with wandb_init() as run:
        tables_2 = wandb.Artifact("tables_2", "database")
        upstream = run.use_artifact("tables:latest")

        # Able to add by reference
        jt = wandb.JoinedTable(
            upstream.get_entry("src_table_1"),
            upstream.get_entry("src_table_2"),
            join_key="id",
        )
        tables_2.add(jt, "jt")
        run.log_artifact(tables_2)

    _cleanup()
    with wandb_init() as run:
        tables_2 = run.use_artifact("tables_2:latest")
        jt_2 = tables_2.get("jt")
        assert (
            wandb.JoinedTable(
                upstream.get("src_table_1"),
                upstream.get("src_table_2"),
                join_key="id",
            )
            == jt_2
        )


def test_image_reference_with_preferred_path(wandb_init, tmp_assets_dir, cleanup):
    orig_im_path = str(tmp_assets_dir / "test.png")
    orig_im_path_2 = str(tmp_assets_dir / "test2.png")
    desired_artifact_path = "images/sample.png"
    with wandb_init() as run:
        artifact = wandb.Artifact("artifact_1", type="test_artifact")
        # manually add the image to a desired path
        artifact.add_file(orig_im_path, desired_artifact_path)
        # create an image that uses this image (it should be smart enough not to add the image twice)
        image = wandb.Image(orig_im_path)
        image_2 = wandb.Image(orig_im_path_2)  # this one doesn't have the path preadded

        # add the image to the table
        table = wandb.Table(["image"], data=[[image], [image_2]])
        # add the table to the artifact
        artifact.add(table, "table")
        run.log_artifact(artifact)

    _cleanup()
    with wandb_init() as run:
        artifact_1 = run.use_artifact("artifact_1:latest")
        original_table = artifact_1.get("table")

        artifact = wandb.Artifact("artifact_2", type="test_artifact")

        # add the image by reference
        image = wandb.Image(original_table.data[0][0])
        image_2 = wandb.Image(original_table.data[1][0])
        # add the image to the table
        table = wandb.Table(["image"], data=[[image], [image_2]])
        # add the table to the artifact
        artifact.add(table, "table")
        run.log_artifact(artifact)

    _cleanup()
    with wandb_init() as run:
        artifact_2 = run.use_artifact("artifact_2:latest")
        artifact_2.download()

    # This test just checks that all this logic does not fail


def test_simple_partition_table(wandb_init, cleanup):
    table_name = "dataset"
    table_parts_dir = "dataset_parts"
    artifact_name = "simple_dataset"
    artifact_type = "dataset"
    columns = ["A", "B", "C"]
    data = []

    # Add Data
    run = wandb_init()
    artifact = wandb.Artifact(artifact_name, type=artifact_type)
    for i in range(5):
        row = [i, i * i, 2**i]
        data.append(row)
        table = wandb.Table(columns=columns, data=[row])
        artifact.add(table, f"{table_parts_dir!s}/{i}")
    partition_table = wandb.data_types.PartitionedTable(parts_path=table_parts_dir)
    artifact.add(partition_table, table_name)
    run.log_artifact(artifact)
    run.finish()

    # test
    run = wandb_init()
    partition_table = run.use_artifact(f"{artifact_name!s}:latest").get(table_name)
    for ndx, row in partition_table.iterrows():
        assert row == data[ndx]
    run.finish()


def test_distributed_artifact_simple(wandb_init, cleanup):
    artifact_name = f"simple_dist_dataset_{round(time.time())}"
    group_name = f"test_group_{np.random.rand()}"
    artifact_type = "distributed_dataset"
    count = 2
    images = []
    image_paths = []

    # Add Data
    for i in range(count):
        with wandb_init(group=group_name) as run:
            artifact = wandb.Artifact(artifact_name, type=artifact_type)

            image = wandb.Image(np.random.randint(0, 255, (10, 10)))
            path = f"image_{i}"

            images.append(image)
            image_paths.append(path)

            artifact.add(image, path)
            run.upsert_artifact(artifact)

    # TODO: Should we try to use_artifact in some way before it is finished?

    # Finish
    with wandb_init(group=group_name) as run:
        artifact = wandb.Artifact(artifact_name, type=artifact_type)
        run.finish_artifact(artifact)

    # test
    with wandb_init() as run:
        artifact = run.use_artifact(f"{artifact_name!s}:latest")

    assert len(artifact.manifest.entries) == count * 2


@pytest.fixture
def cleanup():
    yield
    _cleanup()


def _cleanup():
    # pass
    # # with suppress(OSError):
    # #     shutil.rmtree("wandb")
    with suppress(OSError):
        shutil.rmtree("artifacts")
    with suppress(OSError):
        shutil.rmtree("upstream")


@pytest.fixture
def anon_s3_handler(monkeypatch):
    def init_boto(self):
        if self._s3 is not None:
            return self._s3
        self._botocore = botocore
        self._s3 = boto3.session.Session().resource(
            "s3", config=botocore.client.Config(signature_version=botocore.UNSIGNED)
        )
        return self._s3

    monkeypatch.setattr(S3Handler, "init_boto", init_boto)
    yield


@pytest.fixture
def anon_gcs_handler(monkeypatch):
    def init_gcs(self):
        if self._client is not None:
            return self._client
        self._client = google.cloud.storage.Client.create_anonymous_client()
        return self._client

    monkeypatch.setattr(GCSHandler, "init_gcs", init_gcs)
    yield


@pytest.fixture
def anon_cloud_handlers(anon_gcs_handler, anon_s3_handler):
    yield
