from __future__ import annotations

import hashlib
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import wandb
from PIL import Image as PILImage
from wandb.sdk.data_types import _eval_table_media_ces


@pytest.fixture
def run_factory(mock_run, tmp_path):
    def make(run_id: str):
        run = mock_run(
            settings={
                "entity": "entity",
                "project": "project",
                "run_id": run_id,
                "root_dir": str(tmp_path / run_id),
                "mode": "online",
            }
        )
        run._publish_file = MagicMock()
        return run

    return make


def _png(tmp_path, name="image.png", color=(10, 20, 30)):
    path = tmp_path / name
    PILImage.new("RGB", (2, 2), color=color).save(path)
    return path


def test_ces_eval_table_has_no_supported_media_types():
    image = wandb.Image(PILImage.new("RGB", (1, 1)))

    assert not _eval_table_media_ces.is_supported_wandb_media(image)


def test_run_file_uri_preserves_eval_table_key_path():
    run = SimpleNamespace(entity="team-name", project="project-1", id="run-1")

    uri = _eval_table_media_ces._run_file_uri(
        run,
        "media/eval_tables/images/eval/key/image.png",
    )

    assert uri == (
        "wandb-run-file://team-name/project-1/run-1/"
        "media/eval_tables/images/eval/key/image.png"
    )


def test_committed_artifact_media_returns_artifact_ref_url(tmp_path, monkeypatch):
    image = wandb.Image(_png(tmp_path))
    artifact_ref_url = "wandb-artifact://abc123/media/images/image.png"
    monkeypatch.setattr(
        image,
        "_get_artifact_entry_ref_url",
        lambda: artifact_ref_url,
    )

    assert _eval_table_media_ces._committed_artifact_ref_url(image) == artifact_ref_url


def test_unbound_media_is_bound_in_place_to_eval_table_path(run_factory, tmp_path):
    run = run_factory("run-one")
    path = _png(tmp_path)
    image = wandb.Image(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    uri = _eval_table_media_ces._bind_eval_table_media_to_run(image, run, "eval/key")

    expected_path = os.path.join(
        "media",
        "eval_tables",
        "images",
        "eval",
        "key",
        f"{digest[:20]}.png",
    )
    assert image._run is run
    assert image._path == os.path.join(run.dir, expected_path)
    assert uri.endswith(expected_path.replace(os.sep, "/"))
    run._publish_file.assert_called_once_with(expected_path)


def test_existing_matching_run_file_is_replaced_and_published(run_factory, tmp_path):
    run = run_factory("run-one")
    first_path = _png(tmp_path, "first.png")
    second_path = tmp_path / "second.png"
    second_path.write_bytes(first_path.read_bytes())
    first = wandb.Image(first_path)
    second = wandb.Image(second_path)

    _eval_table_media_ces._bind_eval_table_media_to_run(first, run, "eval")
    run._publish_file.reset_mock()
    uri = _eval_table_media_ces._bind_eval_table_media_to_run(second, run, "eval")

    assert second._run is run
    assert uri.endswith(f"/{second._sha256[:20]}.png")
    run._publish_file.assert_called_once()


def test_media_already_bound_to_active_run_reuses_existing_path(
    run_factory,
    tmp_path,
):
    run = run_factory("run-one")
    image = wandb.Image(_png(tmp_path))
    image.bind_to_run(run, "legacy", 7)
    existing_path = image._path
    run._publish_file.reset_mock()

    uri = _eval_table_media_ces._bind_eval_table_media_to_run(image, run, "eval")

    assert image._path == existing_path
    assert "/media/images/legacy_7_" in uri
    run._publish_file.assert_not_called()


def test_media_for_another_run_is_copied_before_binding(run_factory, tmp_path):
    source_run = run_factory("source-run")
    destination_run = run_factory("destination-run")
    image = wandb.Image(_png(tmp_path))
    image.bind_to_run(source_run, "legacy", 0)
    original_path = image._path

    working_image = _eval_table_media_ces._media_for_run(image, destination_run)
    uri = _eval_table_media_ces._bind_eval_table_media_to_run(
        working_image, destination_run, "eval"
    )

    assert image._run is source_run
    assert image._path == original_path
    assert working_image is not image
    assert uri.startswith("wandb-run-file://entity/project/destination-run/")
    destination_run._publish_file.assert_called_once()
