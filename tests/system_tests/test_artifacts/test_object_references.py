from __future__ import annotations

import shutil
import time
from contextlib import suppress
from pathlib import Path
from typing import Callable, Literal

import boto3
import botocore
import google.cloud.storage
import numpy as np
import wandb
from bokeh.plotting import figure
from pytest import MonkeyPatch, TempPathFactory, fail, fixture, raises
from wandb.data_types import WBValue
from wandb.sdk.lib.hashutil import b64_to_hex_id

TABLE_COLUMNS = [
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

TEST_ASSETS_DIR = Path(__file__).parent.parent.parent / "assets"

IMAGE_FILENAME_1 = "test.png"
IMAGE_FILENAME_2 = "test2.png"


@fixture(scope="session")
def tmp_assets_dir(tmp_path_factory: TempPathFactory) -> Path:
    """A temporary folder with copies of needed test assets for these tests."""
    tmp_dir = tmp_path_factory.mktemp("assets")

    # Copy the test assets to the temporary directory to avoid accidental
    # modification of the original assets.
    shutil.copy(TEST_ASSETS_DIR / IMAGE_FILENAME_1, tmp_dir / IMAGE_FILENAME_1)
    shutil.copy(TEST_ASSETS_DIR / IMAGE_FILENAME_2, tmp_dir / IMAGE_FILENAME_2)
    return tmp_dir


@fixture(scope="session")
def image_path_1(tmp_assets_dir: Path) -> Path:
    return tmp_assets_dir / IMAGE_FILENAME_1


@fixture(scope="session")
def image_path_2(tmp_assets_dir: Path) -> Path:
    return tmp_assets_dir / IMAGE_FILENAME_2


# ---------------------------------------------------------------------------
# Session-scoped factories for creating wandb objects
@fixture(scope="session")
def make_image() -> Callable[[Path], wandb.Image]:
    """Factory for creating wandb.Image objects."""

    def _make_wandb_image(image_path: Path) -> wandb.Image:
        class_labels = {1: "tree", 2: "car", 3: "road"}
        file_path = str(image_path)
        return wandb.Image(
            file_path,
            classes=wandb.Classes(
                [
                    {"id": 1, "name": "tree"},
                    {"id": 2, "name": "car"},
                    {"id": 3, "name": "road"},
                ]
            ),
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
                "ground_truth": {"path": file_path, "class_labels": class_labels},
            },
        )

    return _make_wandb_image


@fixture(scope="session")
def make_point_cloud() -> Callable[[], wandb.Object3D]:
    """Factory for creating wandb.Object3D objects."""

    def _make_point_cloud() -> wandb.Object3D:
        # Generate a symmetric pattern
        point_count = 20_000

        # Choose a random sample
        theta = np.random.rand(point_count)
        chi = np.random.rand(point_count)

        def wave_pattern(theta: np.ndarray, chi: np.ndarray, i: int) -> np.ndarray:
            i2 = i * i

            sin_theta = np.sin(theta)
            cos_theta = np.cos(theta)
            sin_chi = np.sin(chi)
            cos_chi = np.cos(chi)

            p = 4.5 * sin_theta * np.sin(i2 / 2 + i + 1) + 7 * cos_chi * np.sin(i2 - 4)

            x = p * sin_chi * cos_theta
            y = p * sin_chi * sin_theta
            z = p * cos_chi

            r = sin_theta * 120 + 120
            g = np.sin(x) * 120 + 120
            b = np.cos(y) * 120 + 120

            return np.column_stack([x, y, z, r, g, b])

        return wandb.Object3D(wave_pattern(theta, chi, 0))

    return _make_point_cloud


@fixture(scope="session")
def make_bokeh() -> Callable[[], wandb.Bokeh]:
    """Factory for creating wandb.Bokeh objects."""

    def _make_bokeh() -> wandb.Bokeh:
        x = [1, 2, 3, 4, 5]
        y = [6, 7, 2, 4, 5]
        p = figure(title="simple line example", x_axis_label="x", y_axis_label="y")
        p.line(x, y, legend_label="Temp.", line_width=2)

        return wandb.data_types.Bokeh(p)

    return _make_bokeh


@fixture(scope="session")
def make_html() -> Callable[[], wandb.Html]:
    """Factory for creating wandb.Html objects."""

    def _make_html() -> wandb.Html:
        return wandb.Html("<p>Embedded</p><iframe src='https://wandb.ai'></iframe>")

    return _make_html


@fixture(scope="session")
def make_video() -> Callable[[], wandb.Video]:
    """Factory for creating wandb.Video objects."""

    def _make_video() -> wandb.Video:
        # time, channel, height, width
        return wandb.Video(
            np.random.randint(0, high=255, size=(4, 3, 10, 10), dtype=np.uint8)
        )

    return _make_video


@fixture(scope="session")
def make_audio() -> Callable[[int, str], wandb.Audio]:
    """Factory for creating wandb.Audio objects."""

    def _make_wandb_audio(
        frequency: int = 440, caption: str = "four forty"
    ) -> wandb.Audio:
        sample_rate = 44_100
        duration_seconds = 1

        data = np.sin(
            2
            * np.pi
            * np.arange(sample_rate * duration_seconds)
            * frequency
            / sample_rate
        )
        return wandb.Audio(data, sample_rate, caption)

    return _make_wandb_audio


_AUDIO_REF_URIS = {
    "https": "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav",
    "s3": "s3://wandb-artifacts-refs-public-test/StarWars3.wav",
    "gs": "gs://wandb-artifact-refs-public-test/StarWars3.wav",
}


@fixture(scope="session")
def make_audio_ref() -> Callable[[Literal["https", "s3", "gs"]], wandb.Audio]:
    """Factory for creating reference wandb.Audio objects."""

    def _make_wandb_audio_ref(uri_scheme: Literal["https", "s3", "gs"]) -> wandb.Audio:
        uri = _AUDIO_REF_URIS[uri_scheme]
        return wandb.Audio(uri, caption=f"star wars {uri_scheme}")

    return _make_wandb_audio_ref


@fixture(scope="session")
def make_table(
    image_path_1,
    image_path_2,
    make_image,
    make_point_cloud,
    make_html,
    make_video,
    make_bokeh,
    make_audio,
    make_audio_ref,
) -> Callable[[], wandb.Table]:
    """Factory for creating wandb.Table objects."""
    # Reuse these values across the session
    pc1 = make_point_cloud()
    pc2 = make_point_cloud()
    pc3 = make_point_cloud()
    pc4 = make_point_cloud()

    vid1 = make_video()
    vid2 = make_video()
    vid3 = make_video()
    vid4 = make_video()

    b1 = make_bokeh()
    b2 = make_bokeh()
    b3 = make_bokeh()
    b4 = make_bokeh()

    np_data = np.random.randint(255, size=(4, 16, 16, 3))

    def _make_wandb_table() -> wandb.Table:
        classes = wandb.Classes(
            [
                {"id": 1, "name": "tree"},
                {"id": 2, "name": "car"},
                {"id": 3, "name": "road"},
            ]
        )
        table = wandb.Table(
            # Exclude the last column, which will be added via a numpy array
            columns=TABLE_COLUMNS[:-1],
            data=[
                [
                    1,
                    1,
                    "string1",
                    True,
                    1,
                    1.1,
                    make_image(image_path_1),
                    pc1,
                    make_html(),
                    vid1,
                    b1,
                    make_audio(),
                ],
                [
                    2,
                    2,
                    "string2",
                    True,
                    1,
                    1.2,
                    make_image(image_path_1),
                    pc2,
                    make_html(),
                    vid2,
                    b2,
                    make_audio_ref("https"),
                ],
                [
                    3,
                    1,
                    "string3",
                    False,
                    -0,
                    -1.3,
                    make_image(image_path_2),
                    pc3,
                    make_html(),
                    vid3,
                    b3,
                    make_audio_ref("s3"),
                ],
                [
                    4,
                    3,
                    "string4",
                    False,
                    -0,
                    -1.4,
                    make_image(image_path_2),
                    pc4,
                    make_html(),
                    vid4,
                    b4,
                    make_audio_ref("gs"),
                ],
            ],
        )
        table.cast("class_id", classes.get_type())

        # Add the last column from numpy array data
        table.add_column(TABLE_COLUMNS[-1], np_data)

        return table

    return _make_wandb_table


@fixture(scope="session")
def make_joined_table(
    make_table: Callable[[], wandb.Table],
) -> Callable[[], wandb.JoinedTable]:
    """Factory for creating wandb.JoinedTable objects."""

    def _make_wandb_joinedtable() -> wandb.JoinedTable:
        return wandb.JoinedTable(make_table(), make_table(), "id")

    return _make_wandb_joinedtable


# ---------------------------------------------------------------------------
# Function-scoped fixtures of wandb objects
@fixture
def image(make_image, image_path_1) -> wandb.Image:
    """A single wandb.Image object from an image file."""
    return make_image(image_path_1)


@fixture
def image_pair(
    make_image, image_path_1, image_path_2
) -> tuple[wandb.Image, wandb.Image]:
    """A pair of wandb.Image objects from two different image files."""
    return make_image(image_path_1), make_image(image_path_2)


@fixture
def point_cloud(make_point_cloud) -> wandb.Object3D:
    return make_point_cloud()


@fixture
def bokeh(make_bokeh) -> wandb.Bokeh:
    return make_bokeh()


@fixture
def html(make_html) -> wandb.Html:
    return make_html()


@fixture
def video(make_video) -> wandb.Video:
    return make_video()


@fixture
def audio(make_audio) -> wandb.Audio:
    return make_audio()


@fixture
def audio_ref_https(make_audio_ref) -> wandb.Audio:
    return make_audio_ref("https")


@fixture
def audio_ref_s3(make_audio_ref) -> wandb.Audio:
    return make_audio_ref("s3")


@fixture
def audio_ref_gs(make_audio_ref) -> wandb.Audio:
    return make_audio_ref("gs")


@fixture
def table(make_table) -> wandb.Table:
    return make_table()


@fixture
def joined_table(make_joined_table) -> wandb.JoinedTable:
    return make_joined_table()


# Artifact1.add_reference(artifact_URL) => recursive reference
def test_artifact_add_reference_via_url(user, api, tmp_path: Path):
    """Test adding a reference to an artifact via a URL.

    This test creates three artifacts. The middle artifact references the first
    artifact's file, and the last artifact references the middle artifact's reference.
    The end result of downloading the last artifact in a fresh, forth run, should be
    that all 3 artifacts are downloaded and that the file in the last artifact is
    actually a symlink to the first artifact's file.
    """
    # Artifact type + names
    artifact_type = "database"
    name_1 = "upstream_artifact"
    name_2 = "middle_artifact"
    name_3 = "downstream_artifact"

    # The original file to add to the artifact
    orig_file_path = tmp_path / "upstream/local/path/file.txt"

    # Subpaths within the artifact, at which the file, or the reference to it,
    # will be stored.
    subpath_1 = "upstream/artifact/path/file.txt"
    subpath_2 = "middle/artifact/path/file.txt"
    subpath_3 = "downstream/artifact/path/file.txt"

    # Create the original file to add to the artifact
    orig_text = "Luke, I am your Father!!!!!"
    Path(orig_file_path).parent.mkdir(parents=True, exist_ok=True)
    Path(orig_file_path).write_text(orig_text)

    # Create an artifact with such file stored
    with wandb.init() as run_1:
        artifact = wandb.Artifact(name_1, artifact_type)

        artifact.add_file(orig_file_path, subpath_1)

        run_1.log_artifact(artifact)

    # Create an middle artifact with such file referenced (notice no need to download)
    with wandb.init() as run_2:
        artifact = wandb.Artifact(name_2, artifact_type)

        used_artifact_1 = run_2.use_artifact(f"{name_1}:latest")
        artifact_1_ref = (
            f"wandb-artifact://{b64_to_hex_id(used_artifact_1.id)}/{subpath_1!s}"
        )
        artifact.add_reference(artifact_1_ref, subpath_2)

        run_2.log_artifact(artifact)

    # Create a downstream artifact that is referencing the middle's reference
    with wandb.init() as run_3:
        artifact = wandb.Artifact(name_3, artifact_type)

        used_artifact_2 = run_3.use_artifact(f"{name_2}:latest")
        artifact_2_ref = (
            f"wandb-artifact://{b64_to_hex_id(used_artifact_2.id)}/{subpath_2!s}"
        )
        artifact.add_reference(artifact_2_ref, subpath_3)

        run_3.log_artifact(artifact)

    # Finally, download the artifact and check that the file is
    # where we expect it, with the contents of the original file.
    last_artifact = api.artifact(f"{name_3}:latest")

    downloaded_dir = last_artifact.download()

    downloaded_artifact_path = Path(downloaded_dir) / subpath_3
    assert orig_text == downloaded_artifact_path.read_text()

    # Extra consistency check: second download should not fail
    # and should return the same path
    assert downloaded_dir == last_artifact.download()


# # Artifact1.add_reference(artifact2.get_entry(file_name))
def test_add_reference_via_artifact_entry(user, api, tmp_path: Path):
    """Test adding a reference to an artifact via an ArtifactEntry.

    This test is the same as test_artifact_add_reference_via_url, but rather than
    passing the direct URL, we pass an Artifact entry, which will automatically resolve
    to the correct URL.
    """
    # Artifact type + names
    artifact_type = "database"
    name_1 = "upstream_artifact"
    name_2 = "middle_artifact"
    name_3 = "downstream_artifact"

    # The original file to add to the artifact
    orig_file_path = tmp_path / "upstream/local/path/file.txt"

    # Subpaths within the artifact, at which the file, or the reference to it,
    # will be stored.
    subpath_1 = "upstream/artifact/path/file.txt"
    subpath_2 = "middle/artifact/path/file.txt"
    subpath_3 = "downstream/artifact/path/file.txt"

    # Create the original file to add to the artifact
    orig_text = "Luke, I am your Father!!!!!"
    Path(orig_file_path).parent.mkdir(parents=True, exist_ok=True)
    Path(orig_file_path).write_text(orig_text)

    # Create a super important file
    with wandb.init() as run_1:
        artifact_1 = wandb.Artifact(name_1, artifact_type)

        artifact_1.add_file(orig_file_path, subpath_1)

        run_1.log_artifact(artifact_1)

    # Create an middle artifact with such file referenced (notice no need to download)
    with wandb.init() as run_2:
        artifact_2 = wandb.Artifact(name_2, artifact_type)

        used_artifact_1 = run_2.use_artifact(f"{name_1}:latest")
        artifact_1_ref = used_artifact_1.get_entry(subpath_1)
        artifact_2.add_reference(artifact_1_ref, subpath_2)

        run_2.log_artifact(artifact_2)

    # Create a downstream artifact that is referencing the middle's reference
    with wandb.init() as run_3:
        artifact_3 = wandb.Artifact(name_3, artifact_type)

        used_artifact_2 = run_3.use_artifact(f"{name_2}:latest")
        artifact_2_ref = used_artifact_2.get_entry(subpath_2)
        artifact_3.add_reference(artifact_2_ref, subpath_3)

        run_3.log_artifact(artifact_3)

    # Finally, download the artifact and check that the file is
    # where we expect it, with the contents of the original file.
    last_artifact = api.artifact(f"{name_3}:latest")

    downloaded_dir = last_artifact.download()

    downloaded_artifact_path = Path(downloaded_dir) / subpath_3
    assert orig_text == downloaded_artifact_path.read_text()

    # Extra consistency check: second download should not fail
    # and should return the same path
    assert downloaded_dir == last_artifact.download()


# # Artifact1.get(MEDIA_NAME) => media obj
def test_get_artifact_obj_by_name(
    user,
    api,
    image_pair,
    table,
    anon_storage_handlers,
):
    """Test the ability to instantiate a wandb Media object from the name of the object.

    This is the logical inverse of Artifact.add(name).
    """
    artifact_name = "A2"
    artifact_type = "database"

    image_1, image_2 = image_pair

    # TODO: test more robustly for every Media type, nested objects (eg. Table -> Image), and references.
    with wandb.init() as run:
        artifact = wandb.Artifact(artifact_name, artifact_type)
        artifact.add(image_1, "I1")
        artifact.add(table, "T1")
        run.log_artifact(artifact)

    artifact = api.artifact(f"{artifact_name}:latest")
    actual_image = artifact.get("I1")
    assert actual_image == image_1

    actual_table = artifact.get("T1")
    assert actual_table.columns == table.columns

    image_col_idx = table.columns.index("Image")
    assert actual_table.data[0][image_col_idx] == image_1
    assert actual_table.data[1][image_col_idx] == image_2

    actual_table._eq_debug(table, True)
    assert actual_table == table


# # Artifact1.add(artifact2.get(MEDIA_NAME))
def test_adding_artifact_by_object(user, api, image):
    """Test adding wandb Media objects to an artifact by passing the object itself."""

    # Create an artifact with such file stored
    with wandb.init() as run:
        artifact = wandb.Artifact("upstream_media", "database")

        artifact.add(image, "I1")

        run.log_artifact(artifact)

    # Create an middle artifact with such file referenced (notice no need to download)
    with wandb.init() as run:
        artifact = wandb.Artifact("downstream_media", "database")

        upstream_artifact = run.use_artifact("upstream_media:latest")
        artifact.add(upstream_artifact.get("I1"), "T2")

        run.log_artifact(artifact)

    downstream_artifact = api.artifact("downstream_media:latest")
    downstream_artifact.download()
    assert downstream_artifact.get("T2") == image


def test_image_reference_artifact(user, api, image, cleanup_temp_subdirs):
    with wandb.init() as run:
        artifact = wandb.Artifact("image_data", "data")
        artifact.add(image, "image")
        run.log_artifact(artifact)

    with wandb.init() as run:
        artifact_1 = run.use_artifact("image_data:latest")
        artifact = wandb.Artifact("reference_data", "data")
        artifact.add(artifact_1.get("image"), "image_2")
        run.log_artifact(artifact)

    cleanup_temp_subdirs()

    artifact_2 = api.artifact("reference_data:latest")
    artifact_2.download()


def test_nested_reference_artifact(user, api, image):
    with wandb.init() as run:
        artifact = wandb.Artifact("image_data", "data")
        artifact.add(image, "image")
        run.log_artifact(artifact)

    with wandb.init() as run:
        artifact_1 = run.use_artifact("image_data:latest")
        artifact = wandb.Artifact("reference_data", "data")
        table = wandb.Table(["image"], [[artifact_1.get("image")]])
        artifact.add(table, "table_2")
        run.log_artifact(artifact)

    artifact_3 = api.artifact("reference_data:latest")
    table_2 = artifact_3.get("table_2")

    table._eq_debug(table_2, True)
    assert table == table_2
    artifact_3.download()


def test_table_slice_reference_artifact(
    user,
    api,
    table,
    cleanup_temp_subdirs: Callable[[], None],
    anon_storage_handlers: None,
):
    with wandb.init() as run:
        artifact = wandb.Artifact("table_data", "data")
        artifact.add(table, "table")
        run.log_artifact(artifact)

    with wandb.init() as run:
        artifact_1 = run.use_artifact("table_data:latest")
        t1 = artifact_1.get("table")
        artifact = wandb.Artifact("intermediate_data", "data")
        i1 = wandb.Table(t1.columns, t1.data[:1])
        i2 = wandb.Table(t1.columns, t1.data[1:])
        artifact.add(i1, "table1")
        artifact.add(i2, "table2")
        run.log_artifact(artifact)

    with wandb.init() as run:
        artifact_2 = run.use_artifact("intermediate_data:latest")
        i1 = artifact_2.get("table1")
        i2 = artifact_2.get("table2")
        artifact = wandb.Artifact("reference_data", "data")
        table1 = wandb.Table(t1.columns, i1.data)
        table2 = wandb.Table(t1.columns, i2.data)
        artifact.add(table1, "table1")
        artifact.add(table2, "table2")
        run.log_artifact(artifact)

    cleanup_temp_subdirs()

    artifact_3 = api.artifact("reference_data:latest")
    table1 = artifact_3.get("table1")
    table2 = artifact_3.get("table2")

    assert not Path(artifact_2._default_root()).is_dir()

    def assert_eq_data(d1, d2):
        assert len(d1) == len(d2)
        for ndx in range(len(d1)):
            assert len(d1[ndx]) == len(d2[ndx])
            for i in range(len(d1[ndx])):
                eq = d1[ndx][i] == d2[ndx][i]
                if isinstance(eq, (list, np.ndarray)):
                    assert np.all(eq)
                else:
                    assert eq

    assert_eq_data(t1.data[:1], table1.data)
    assert_eq_data(t1.data[1:], table2.data)


class TestMediaObjectReferentialEquality:
    @fixture(
        params=[
            table.__name__,
            image.__name__,
            point_cloud.__name__,
            bokeh.__name__,
            html.__name__,
            video.__name__,
            joined_table.__name__,
            audio_ref_https.__name__,
            audio_ref_s3.__name__,
            audio_ref_gs.__name__,
        ]
    )
    def orig_obj(self, request) -> WBValue:
        return request.getfixturevalue(request.param)

    def test_media_obj_referential_equality(
        self, user, api, anon_storage_handlers, orig_obj, worker_id
    ):
        """General consistency check on media object references.

        In detail, this will check the following:

        - Add the object to an artifact
            Validate that "getting" this asset returns an object that is equal to the first
        - Add a reference to this asset in an intermediate artifact
            Validate that "getting" this reference asset returns an object that is equal to the first
            Validate that the symbolic links are proper
        - Add a reference to the intermediate reference in yet a third artifact
            Validate that "getting" this new reference asset returns an object that is equal to the first
            Validate that the intermediate object is not downloaded - there are no "leftover" assets (eg. classes.json)
            Validate that the symbolic links are proper
        """
        # Name these temporary artifacts by worker ID to guard against race
        # conditions between parallel pytest-xdist processes.
        orig_name = f"orig-artifact-{worker_id}"
        mid_name = f"mid-artifact-{worker_id}"
        down_name = f"down-artifact-{worker_id}"

        with wandb.init() as run:
            orig_artifact = wandb.Artifact(orig_name, "database")
            orig_artifact.add(orig_obj, "obj1")
            run.log_artifact(orig_artifact)

        orig_artifact_ref = api.artifact(f"{orig_name}:latest")
        orig_dir = orig_artifact_ref._default_root()
        obj1 = orig_artifact_ref.get("obj1")

        if isinstance(orig_obj, (wandb.Table, wandb.JoinedTable)):
            orig_obj._eq_debug(obj1, True)
        else:
            assert orig_obj == obj1

        assert (Path(orig_dir) / f"obj1.{orig_obj._log_type}.json").is_file()

        with wandb.init() as run:
            orig_artifact_ref = run.use_artifact(f"{orig_name}:latest")

            mid_artifact = wandb.Artifact(mid_name, "database")
            mid_obj = orig_artifact_ref.get("obj1")
            mid_artifact.add(mid_obj, "obj2")

            run.log_artifact(mid_artifact)

        mid_artifact_ref = api.artifact(f"{mid_name}:latest")
        mid_dir = mid_artifact_ref._default_root()
        obj2 = mid_artifact_ref.get("obj2")

        if isinstance(orig_obj, (wandb.Table, wandb.JoinedTable)):
            orig_obj._eq_debug(obj2, True)
        else:
            assert orig_obj == obj2

        with wandb.init() as run:
            mid_artifact_ref = run.use_artifact(f"{mid_name}:latest")

            down_artifact = wandb.Artifact(down_name, "database")
            down_obj = mid_artifact_ref.get("obj2")
            down_artifact.add(down_obj, "obj3")

            run.log_artifact(down_artifact)

        down_artifact_ref = api.artifact(f"{down_name}:latest")
        obj3 = down_artifact_ref.get("obj3")

        if isinstance(orig_obj, (wandb.Table, wandb.JoinedTable)):
            orig_obj._eq_debug(obj3, True)
        else:
            assert orig_obj == obj3

        assert not Path(mid_dir).is_dir()


def test_joined_table_referential(
    user, api, make_image, image_path_1, cleanup_temp_subdirs
):
    src_image_1 = make_image(image_path_1)
    src_image_2 = make_image(image_path_1)
    src_image_3 = make_image(image_path_1)
    src_image_4 = make_image(image_path_1)

    src_table_1 = wandb.Table(["id", "image"], [[1, src_image_1], [2, src_image_2]])
    src_table_2 = wandb.Table(["id", "image"], [[1, src_image_3], [2, src_image_4]])

    src_jt_1 = wandb.JoinedTable(src_table_1, src_table_2, "id")

    with wandb.init() as run:
        orig_artifact = wandb.Artifact("art1", "database")
        orig_artifact.add(src_jt_1, "src_jt_1")
        run.log_artifact(orig_artifact)

    with wandb.init() as run:
        art1 = run.use_artifact("art1:latest")

        src_jt_1 = art1.get("src_jt_1")
        src_jt_2 = wandb.JoinedTable(src_jt_1._table1, src_jt_1._table2, "id")
        art2 = wandb.Artifact("art2", "database")
        art2.add(src_jt_2, "src_jt_2")

        run.log_artifact(art2)

    cleanup_temp_subdirs()

    art2 = api.artifact("art2:latest")
    src_jt_2 = art2.get("src_jt_2")
    src_jt_1._eq_debug(src_jt_2, True)
    assert src_jt_1 == src_jt_2


def test_joined_table_add_by_path(
    user, api, make_image, image_path_1, cleanup_temp_subdirs
):
    artifact_name_1 = "tables_1"
    artifact_name_2 = "tables_2"
    artifact_type = "database"

    src_image_1 = make_image(image_path_1)
    src_image_2 = make_image(image_path_1)
    src_image_3 = make_image(image_path_1)
    src_image_4 = make_image(image_path_1)

    src_table_1 = wandb.Table(["id", "image"], [[1, src_image_1], [2, src_image_2]])
    src_table_2 = wandb.Table(["id", "image"], [[1, src_image_3], [2, src_image_4]])

    table_name_1 = "src_table_1"
    table_name_2 = "src_table_2"

    with wandb.init() as run:
        tables = wandb.Artifact(artifact_name_1, artifact_type)
        tables.add(src_table_1, table_name_1)
        tables.add(src_table_2, table_name_2)

        # Should be able to add by name directly
        jt = wandb.JoinedTable(
            f"{table_name_1}.table.json", f"{table_name_2}.table.json", "id"
        )
        tables.add(jt, "jt")

        # Make sure it errors when you are not referencing the correct table names
        bad_table_name = "bad_table_name"
        jt_bad = wandb.JoinedTable(
            f"{bad_table_name}.table.json", f"{bad_table_name}.table.json", "id"
        )
        with raises(ValueError):
            tables.add(jt_bad, "jt_bad")

        run.log_artifact(tables)

    cleanup_temp_subdirs()
    with wandb.init() as run:
        tables_2 = wandb.Artifact(artifact_name_2, artifact_type)
        upstream = run.use_artifact(f"{artifact_name_1}:latest")

        # Able to add by reference
        jt = wandb.JoinedTable(
            upstream.get_entry(table_name_1), upstream.get_entry(table_name_2), "id"
        )
        tables_2.add(jt, "jt")
        run.log_artifact(tables_2)

    cleanup_temp_subdirs()

    tables_2 = api.artifact(f"{artifact_name_2}:latest")
    jt_2 = tables_2.get("jt")
    assert (
        wandb.JoinedTable(upstream.get(table_name_1), upstream.get(table_name_2), "id")
        == jt_2
    )


def test_image_reference_with_preferred_path(
    user, api, cleanup_temp_subdirs, image_path_1, image_path_2
):
    orig_path_1 = str(image_path_1)
    orig_path_2 = str(image_path_2)
    desired_artifact_path = "images/sample.png"
    with wandb.init() as run:
        artifact = wandb.Artifact("artifact_1", type="test_artifact")

        # manually add the image to a desired path
        artifact.add_file(orig_path_1, desired_artifact_path)

        # create an image that uses this image (it should be smart enough not to add the image twice)
        image_1 = wandb.Image(orig_path_1)
        image_2 = wandb.Image(orig_path_2)  # this one does not have the path preadded

        # add the image to the table
        table = wandb.Table(["image"], data=[[image_1], [image_2]])

        # add the table to the artifact
        artifact.add(table, "table")
        run.log_artifact(artifact)

    cleanup_temp_subdirs()
    with wandb.init() as run:
        artifact_1 = run.use_artifact("artifact_1:latest")
        original_table = artifact_1.get("table")

        artifact = wandb.Artifact("artifact_2", type="test_artifact")

        # add the image by reference
        image_1 = wandb.Image(original_table.data[0][0])
        image_2 = wandb.Image(original_table.data[1][0])
        # add the image to the table
        table = wandb.Table(["image"], data=[[image_1], [image_2]])
        # add the table to the artifact
        artifact.add(table, "table")
        run.log_artifact(artifact)

    cleanup_temp_subdirs()

    artifact_2 = api.artifact("artifact_2:latest")
    artifact_2.download()

    # This test just checks that all this logic does not fail


def test_simple_partition_table(user, api):
    table_name = "dataset"
    table_parts_dir = "dataset_parts"
    artifact_name = "simple_dataset"
    artifact_type = "dataset"
    columns = ["A", "B", "C"]
    data = [[i, i * i, 2**i] for i in range(5)]

    # Add Data
    with wandb.init() as run:
        artifact = wandb.Artifact(artifact_name, type=artifact_type)

        for i, row in enumerate(data):
            table = wandb.Table(columns=columns, data=[row])
            artifact.add(table, f"{table_parts_dir}/{i}")

        partition_table = wandb.data_types.PartitionedTable(parts_path=table_parts_dir)
        artifact.add(partition_table, table_name)

        run.log_artifact(artifact)

    # test
    partition_table = api.artifact(f"{artifact_name}:latest").get(table_name)
    for ndx, row in partition_table.iterrows():
        assert row == data[ndx]


def test_distributed_artifact_simple(user, api):
    # table_name = "dataset"
    artifact_name = f"simple_dist_dataset_{round(time.time())}"
    group_name = f"test_group_{np.random.rand()}"
    artifact_type = "distributed_dataset"
    count = 2
    images = []
    image_paths = []

    # Add Data
    for i in range(count):
        with wandb.init(group=group_name) as run:
            artifact = wandb.Artifact(artifact_name, type=artifact_type)

            image = wandb.Image(np.random.randint(0, 255, (10, 10)))
            path = f"image_{i}"
            images.append(image)
            image_paths.append(path)
            artifact.add(image, path)

            run.upsert_artifact(artifact)

    # Finish
    with wandb.init(group=group_name) as run:
        artifact = wandb.Artifact(artifact_name, type=artifact_type)
        run.finish_artifact(artifact)

    # test
    artifact = api.artifact(f"{artifact_name}:latest")
    assert len(artifact.manifest.entries.keys()) == count * 2
    # for image, path in zip(images, image_paths):
    #     assert image == artifact.get(path)


@fixture
def cleanup_temp_subdirs(tmp_path: Path) -> Callable[[], None]:
    """A function to clean up temporary folders created by tests in this module."""
    # Check that the current working directory is the same or a subdirectory
    # of the tmp_path fixture.  This *should* be ensured by the
    # `filesystem_isolate` fixture, but verify.
    cwd = Path.cwd().resolve()
    try:
        cwd.relative_to(tmp_path)
    except ValueError:
        fail(
            f"Current working directory ({cwd!s}) is not a subpath of temporary "
            f"test directory ({tmp_path!s})"
        )

    cleaned_subdirs = ["wandb", "artifacts", "upstream"]

    def _cleanup() -> None:
        for subdir in cleaned_subdirs:
            with suppress(FileNotFoundError):
                shutil.rmtree(cwd / subdir)

    return _cleanup


@fixture(scope="session")
def anon_storage_handlers():
    from wandb.sdk.artifacts.storage_handlers.gcs_handler import GCSHandler
    from wandb.sdk.artifacts.storage_handlers.s3_handler import S3Handler

    def init_boto(self):
        if self._s3 is not None:
            return self._s3
        self._botocore = botocore
        self._s3 = boto3.session.Session().resource(
            "s3", config=botocore.client.Config(signature_version=botocore.UNSIGNED)
        )
        return self._s3

    def init_gcs(self):
        if self._client is not None:
            return self._client
        self._client = google.cloud.storage.Client.create_anonymous_client()
        return self._client

    # Use MonkeyPatch.context(), as this fixture can/should be session-scoped,
    # while the `monkeypatch` fixture is strictly function-scoped.
    with MonkeyPatch.context() as patcher:
        patcher.setattr(S3Handler, "init_boto", init_boto)
        patcher.setattr(GCSHandler, "init_gcs", init_gcs)
        yield
