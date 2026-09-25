from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import wandb
from PIL import Image as PILImage
from wandb.sdk.data_types.eval_table import _media_ces


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

    assert not _media_ces.is_supported_wandb_media(image)


def test_run_file_uri_preserves_eval_table_key_path():
    run = SimpleNamespace(entity="team-name", project="project-1", id="run-1")

    uri = _media_ces._run_file_uri(
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

    assert _media_ces._committed_artifact_ref_url(image) == artifact_ref_url


def test_media_binds_to_explicit_run_path(run_factory, tmp_path):
    run = run_factory("run-one")
    source = _png(tmp_path)
    image = wandb.Image(source)
    logical_path = os.path.join("media", "eval_tables", "images", "custom.png")

    _media_ces._place_media_file_in_run(image, run, logical_path)

    destination = os.path.join(run.dir, logical_path)
    assert image._run is run
    assert image._path == destination
    assert Path(destination).read_bytes() == source.read_bytes()
    run._publish_file.assert_called_once_with(logical_path)


def test_unbound_media_is_bound_in_place_to_eval_table_path(run_factory, tmp_path):
    run = run_factory("run-one")
    path = _png(tmp_path)
    image = wandb.Image(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    uri = _media_ces._bind_eval_table_media_to_run(image, run, "eval/key")

    expected_path = os.path.join(
        "media",
        "eval_tables",
        "images",
        "eval",
        "key",
        f"{digest[:30]}.png",
    )
    assert image._run is run
    assert image._path == os.path.join(run.dir, expected_path)
    assert uri.endswith(expected_path.replace(os.sep, "/"))
    run._publish_file.assert_called_once_with(expected_path)


def test_media_already_bound_to_active_run_reuses_existing_path(
    run_factory,
    tmp_path,
):
    run = run_factory("run-one")
    image = wandb.Image(_png(tmp_path))
    image.bind_to_run(run, "legacy", 7)
    existing_path = image._path
    run._publish_file.reset_mock()

    working_image = _media_ces._media_for_run(image, run)
    uri = _media_ces._bind_eval_table_media_to_run(working_image, run, "eval")

    assert working_image is image
    assert image._path == existing_path
    assert "/media/images/legacy_7_" in uri
    run._publish_file.assert_not_called()


def test_media_for_another_run_is_copied_before_binding(run_factory, tmp_path):
    source_run = run_factory("source-run")
    destination_run = run_factory("destination-run")
    image = wandb.Image(_png(tmp_path))
    image.bind_to_run(source_run, "legacy", 0)
    original_path = image._path

    working_image = _media_ces._media_for_run(image, destination_run)
    uri = _media_ces._bind_eval_table_media_to_run(
        working_image, destination_run, "eval"
    )

    assert image._run is source_run
    assert image._path == original_path
    assert working_image is not image
    assert uri.startswith("wandb-run-file://entity/project/destination-run/")
    destination_run._publish_file.assert_called_once()
