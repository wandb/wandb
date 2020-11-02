# Suggest running as: WANDB_BASE_URL=http://api.wandb.test python artifact_object_reference_test.py                                                               timothysweeney@Timothys-MacBook-Pro
import shutil
import wandb
import os

classes = [{"id": 0, "name": "person"}]
columns = ["examples", "index"]
PROJECT_NAME = "test_project_art"


def _make_wandb_image(suffix=""):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "test" + str(suffix) + ".png")
    return wandb.Image(im_path, classes=classes)


def _assert_wandb_image_compare(image, suffix=""):
    assert isinstance(image, wandb.Image)
    assert image._image == _make_wandb_image(suffix)._image
    assert image._classes._class_set == classes


def _make_wandb_table():
    table = wandb.Table(columns)
    table.add_data(_make_wandb_image(), 1)
    table.add_data(_make_wandb_image(2), 2)
    return table


def _make_joined_table():
    table_1 = _make_wandb_table()
    table_2 = _make_wandb_table()
    return wandb.JoinedTable(table_1, table_2, "index")


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
            "wandb-artifact://{}/{}".format(str(upstream_artifact.id),str(upstream_artifact_file_path)),
            middle_artifact_file_path,
        )
        run.log_artifact(artifact)

    # Create a downstream artifact that is referencing the middle's reference
    with wandb.init(project=PROJECT_NAME) as run:
        artifact = wandb.Artifact(downstream_artifact_name, "database")
        middle_artifact = run.use_artifact(middle_artifact_name + ":latest")
        artifact.add_reference(
            "wandb-artifact://{}/{}".format(str(middle_artifact.id),str(middle_artifact_file_path)),
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
        assert os.path.islink(
            os.path.join(downstream_path, downstream_artifact_file_path)
        )
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
        assert os.path.islink(
            os.path.join(downstream_path, downstream_artifact_file_path)
        )
        with open(
            os.path.join(downstream_path, downstream_artifact_file_path), "r"
        ) as file:
            assert file.read() == file_text

# Artifact1.get(MEDIA_NAME) => media obj
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
        _assert_wandb_image_compare(actual_image)

        actual_table = artifact.get("T1")
        assert actual_table.columns == columns
        _assert_wandb_image_compare(actual_table.data[0][0])
        _assert_wandb_image_compare(actual_table.data[1][0], "2")
        assert actual_table.data[0][1] == 1
        assert actual_table.data[1][1] == 2


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
        assert os.path.islink(os.path.join(downstream_path, "T2.image-file.json"))
        _assert_wandb_image_compare(downstream_artifact.get("T2"))


def _cleanup():
    if os.path.isdir("wandb"):
        shutil.rmtree("wandb")
    if os.path.isdir("artifacts"):
        shutil.rmtree("artifacts")


if __name__ == "__main__":
    try:
        test_artifact_add_reference_via_url()
        _cleanup()
        test_add_reference_via_artifact_entry()
        _cleanup()
        test_adding_artifact_by_object()
        _cleanup()
        test_get_artifact_obj_by_name()
        _cleanup()
    finally:
        _cleanup()