"""Test wandb.Image."""

import os
import platform
from pathlib import Path

import numpy as np
import pytest
import responses
import wandb
from wandb.sdk.data_types import utils

try:
    from PIL import Image as PILImage
except ImportError:
    pytest.skip("pillow is not installed", allow_module_level=True)


@pytest.fixture
def full_box():
    yield {
        "position": {
            "middle": (0.5, 0.5),
            "width": 0.1,
            "height": 0.2,
        },
        "class_id": 2,
        "box_caption": "This is a big car",
        "scores": {"acc": 0.3},
    }


@pytest.fixture
def dissoc():
    # Helper function return a new dictionary with the key removed
    def dissoc_fn(d, key):
        new_d = d.copy()
        new_d.pop(key)
        return new_d

    yield dissoc_fn


@pytest.fixture
def standard_mask():
    yield {
        "mask_data": np.array(
            [
                [1, 2, 2, 2],
                [2, 3, 3, 4],
                [4, 4, 4, 4],
                [4, 4, 4, 2],
            ]
        ),
        "class_labels": {
            1: "car",
            2: "pedestrian",
            3: "tractor",
            4: "cthululu",
        },
    }


@pytest.fixture
def image_media() -> wandb.Image:
    return wandb.Image(np.ones(shape=(32, 32)))


def test_captions():
    images = [
        wandb.Image(np.random.random((28, 28)), caption="Cool"),
        wandb.Image(np.random.random((28, 28)), caption="Nice"),
    ]
    assert wandb.Image.all_captions(images) == ["Cool", "Nice"]


def test_bind_image(mock_run):
    image = wandb.Image(np.random.random((28, 28)))
    image.bind_to_run(mock_run(), "stuff", 10)
    assert image.is_bound()


def test_image_accepts_other_images():
    image_a = wandb.Image(np.random.random((300, 300, 3)))
    image_b = wandb.Image(image_a)
    assert image_a == image_b


def test_image_accepts_bounding_boxes(
    mock_run,
    full_box,
):
    run = mock_run()
    img = wandb.Image(
        np.random.random((28, 28)),
        boxes={
            "predictions": {
                "box_data": [full_box],
            },
        },
    )
    img.bind_to_run(run, "images", 0)
    img_json = img.to_json(run)
    path = img_json["boxes"]["predictions"]["path"]
    assert os.path.exists(os.path.join(run.dir, path))


def test_image_accepts_bounding_boxes_optional_args(
    mock_run,
    full_box,
    dissoc,
):
    optional_keys = ["box_caption", "scores"]

    boxes_with_removed_optional_args = [dissoc(full_box, k) for k in optional_keys]

    img = wandb.Image(
        np.random.random((28, 28)),
        boxes={
            "predictions": {
                "box_data": boxes_with_removed_optional_args,
            },
        },
    )
    run = mock_run()
    img.bind_to_run(run, "images", 0)
    img_json = img.to_json(run)
    path = img_json["boxes"]["predictions"]["path"]
    assert os.path.exists(os.path.join(run.dir, path))


def test_image_accepts_masks(
    mock_run,
    standard_mask,
):
    img = wandb.Image(
        np.random.random((28, 28)),
        masks={
            "overlay": standard_mask,
        },
    )
    run = mock_run()
    img.bind_to_run(run, "images", 0)
    img_json = img.to_json(run)
    path = img_json["masks"]["overlay"]["path"]
    assert os.path.exists(os.path.join(run.dir, path))


def test_image_accepts_masks_without_class_labels(
    mock_run,
    dissoc,
    standard_mask,
):
    img = wandb.Image(
        np.random.random((28, 28)),
        masks={
            "overlay": dissoc(standard_mask, "class_labels"),
        },
    )
    run = mock_run()
    img.bind_to_run(run, "images", 0)
    img_json = img.to_json(run)
    path = img_json["masks"]["overlay"]["path"]
    assert os.path.exists(os.path.join(run.dir, path))


def test_image_seq_to_json(
    mock_run,
):
    run = mock_run()
    image = wandb.Image(np.random.random((28, 28)))
    image.bind_to_run(run, "test", 0, 0)
    wandb.Image.seq_to_json([image], run, "test", 0)
    assert os.path.exists(os.path.join(run.dir, "media", "images", "test_0_0.png"))


def test_max_images(mock_run):
    run = mock_run()
    image = wandb.Image(np.random.randint(255, size=(10, 10)))
    images = [image] * 200
    images[0].bind_to_run(run, "test2", 0, 0)
    metadata = wandb.Image.seq_to_json(
        utils._prune_max_seq(images),
        run,
        "test2",
        0,
    )
    assert metadata["_type"] == "images/separated"
    assert metadata["count"] == wandb.Image.MAX_ITEMS
    assert metadata["height"] == 10
    assert metadata["width"] == 10
    assert os.path.exists(os.path.join(run.dir, "media/images/test2_0_0.png"))


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Windows doesn't support symlinks"
)
def test_image_refs():
    with responses.RequestsMock() as response:
        # Set up a response for the image
        url = "http://nonexistent/puppy.jpg"
        response.add(
            method="GET",
            url=url,
            body=b"test",
            headers={"etag": "testEtag", "content-length": "200"},
        )

        # Create the image
        image = wandb.Image(url)

        # Create the artifact
        artifact = wandb.Artifact("image_ref_test", "images")
        artifact.add(image, "image_ref")

        # Check the metadata
        expected_sha256 = (
            "75c13e5a637fb8052da99792fca8323c06b138966cd30482e84d62c83adc01ee"
        )
        expected_path = f"media/images/{expected_sha256[:20]}/puppy.jpg"

        # Check the image serialization metadata
        expected_metadata = {
            "path": expected_path,
            "sha256": expected_sha256,
            "_type": "image-file",
            "format": "jpg",
        }
        assert image.to_json(artifact) == expected_metadata

        # Check the artifact manifest
        manifest_expected = {
            "image_ref.image-file.json": {
                "digest": "SZvdv5ouAEq2DEOgVBwOog==",
                "size": 173,
            },
            expected_path: {
                "digest": "testEtag",
                "ref": url,
                "extra": {"etag": "testEtag"},
                "size": 200,
            },
        }
        manifest = artifact.manifest.to_manifest_json()
        assert manifest["contents"] == manifest_expected


def test_guess_mode():
    image = wandb.Image(np.random.randint(255, size=(28, 28, 3)))
    assert image.image is not None
    assert image.image.mode == "RGB"


def test_pil():
    img = PILImage.new("L", (28, 28))
    wb_img = wandb.Image(img)
    assert wb_img.image is not None
    assert list(wb_img.image.getdata()) == list(img.getdata())  # type: ignore


@pytest.mark.parametrize(
    "invalid_character",
    [
        "<",
        ">",
        ":",
        "\\",
        "?",
        "*",
    ],
)
@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
def test_log_media_with_invalid_character_on_windows(
    mock_run, image_media, invalid_character
):
    run = mock_run()
    with pytest.raises(ValueError, match="Media .* is invalid"):
        image_media.bind_to_run(run, f"image{invalid_character}test", 0)


def test_log_media_with_path_traversal(mock_run, image_media):
    run = mock_run()
    image_media.bind_to_run(run, "../../../image", 0)

    # Resolve to path to verify no path traversals
    resolved_path = str(Path(image_media._path).resolve())
    assert resolved_path.startswith(run.dir)
    assert os.path.exists(resolved_path)


@pytest.mark.parametrize(
    "media_key",
    [
        "////image",
        "my///image",
    ],
)
def test_log_media_prefixed_with_multiple_slashes(mock_run, media_key, image_media):
    run = mock_run()
    image_media.bind_to_run(run, media_key, 0)

    resolved_path = str(Path(image_media._path).resolve())
    assert resolved_path.startswith(run.dir)
    assert os.path.exists(resolved_path)


def test_log_media_saves_to_run_directory(mock_run, image_media):
    run = mock_run(use_magic_mock=True)
    image_media.bind_to_run(run, "/media/path", 0)

    # Assert media object is saved under the run directory
    assert image_media._path.startswith(run.dir)
