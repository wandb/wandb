from __future__ import annotations

import hashlib
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, call

import pytest
from PIL import Image as PILImage

import wandb
from wandb.errors import UsageError
from wandb.sdk.data_types import (
    _eval_table_media_ces,
    _eval_table_writer,
    _eval_table_writer_ces,
)


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
        run._add_singleton = MagicMock()
        return run

    return make


@pytest.fixture
def mock_ces_client(monkeypatch):
    client = MagicMock()
    client.eval_tables.create.return_value = SimpleNamespace(
        dataset_id="dataset-1",
        evaluation_id="evaluation-1",
    )
    client.eval_tables.create_version.return_value = SimpleNamespace(
        dataset_version_id="dataset-version-1",
        evaluation_version_id="evaluation-version-1",
    )
    monkeypatch.setenv("CES_BASE_URL", "https://evaluations.example.test")
    client_module = types.ModuleType("coreweave_evaluations")
    client_module.CoreWeaveEvaluations = MagicMock
    monkeypatch.setitem(sys.modules, "coreweave_evaluations", client_module)
    monkeypatch.setattr(
        _eval_table_writer_ces.CESEvalTableWriter,
        "_resolve_scope_context",
        lambda self, bound: _eval_table_writer_ces._CESScopeContext(
            scope_ref="scope-ref",
            api_key=None,
            access_token="token",
        ),
    )
    monkeypatch.setattr(
        _eval_table_writer_ces.CESEvalTableWriter,
        "_create_client",
        lambda self, client_type, base_url, scope: client,
    )
    return client


def _png(tmp_path, name="image.png", color=(10, 20, 30)):
    path = tmp_path / name
    PILImage.new("RGB", (2, 2), color=color).save(path)
    return path


@pytest.fixture
def artifact_image_factory(tmp_path, monkeypatch):
    def make(
        *,
        name,
        class_labels,
        boxes=None,
        mask_keys=(),
    ):
        image_entry_name = f"media/images/{name}.png"
        image_path = _png(tmp_path, f"{name}.png")
        entries = {
            image_entry_name: SimpleNamespace(
                download=lambda: str(image_path),
                ref=None,
            )
        }
        local_paths = {str(image_path): image_entry_name}
        masks = {}
        for key in mask_keys:
            mask_entry_name = f"media/images/{name}-{key}.png"
            mask_path = _png(tmp_path, f"{name}-{key}.png")
            entries[mask_entry_name] = SimpleNamespace(
                download=lambda path=mask_path: str(path),
                ref=None,
            )
            local_paths[str(mask_path)] = mask_entry_name
            masks[key] = {"path": mask_entry_name}

        source_artifact = MagicMock()
        source_artifact.get.return_value = wandb.Classes(
            [
                {"id": class_id, "name": label}
                for class_id, label in class_labels.items()
            ]
        )
        source_artifact.get_entry.side_effect = entries.__getitem__
        source_artifact._local_path_to_name.side_effect = local_paths.get

        image_json = {
            "path": image_entry_name,
            "format": "png",
            "classes": {"path": f"media/classes/{name}.classes.json"},
        }
        if boxes is not None:
            image_json["boxes"] = boxes
        if masks:
            image_json["masks"] = masks

        # Run metrics use this same artifact rehydration boundary before serialization.
        image = wandb.Image.from_json(image_json, source_artifact)
        artifact_uri = f"wandb-artifact://abc123/{image_entry_name}"
        monkeypatch.setattr(
            image,
            "_get_artifact_entry_ref_url",
            lambda: artifact_uri,
        )
        return image, artifact_uri

    return make


def _image_write_input(image):
    return _eval_table_writer.EvalTableWriteInput(
        name="eval",
        rows=[
            _eval_table_writer.EvalTableWriteRow(
                inputs={"image": image},
                outputs=None,
                scores={},
            )
        ],
        column_keys={"image": "image"},
        ncols=1,
        log_mode="IMMUTABLE",
    )


_IMAGE_FIELD = _eval_table_media_ces.EvalTableMediaField(
    eval_table_key="eval",
    source="inputs",
    column_name="image",
)


def _image_from_external_reference_artifact(tmp_path, monkeypatch):
    image = wandb.Image(_png(tmp_path))
    source_artifact = MagicMock()
    source_artifact._local_path_to_name.return_value = "media/images/image.png"
    source_artifact.get_entry.return_value.ref = "s3://private-bucket/image.png"
    source_artifact.get_entry.return_value._is_artifact_reference.return_value = False
    image._artifact_source = SimpleNamespace(artifact=source_artifact, name=None)
    monkeypatch.setattr(
        image,
        "_get_artifact_entry_ref_url",
        lambda: "wandb-artifact://abc123/media/images/image.png",
    )
    return image


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


def test_ces_eval_table_supports_images():
    image = wandb.Image(PILImage.new("RGB", (1, 1)))

    assert _eval_table_media_ces.is_supported_wandb_media(image)


def test_prepare_image_creates_ces_extension_value(run_factory, tmp_path):
    run = run_factory("run-one")
    path = _png(tmp_path)
    image = wandb.Image(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    prepared = _eval_table_media_ces.prepare_image(image, run, _IMAGE_FIELD)

    assert prepared.value == {
        "sha256": digest,
        "size": path.stat().st_size,
        "format": "png",
        "width": 2,
        "height": 2,
        "extension_type": "wandb-image",
        "schema_version": 1,
        "wb_media_type": "image-file",
        "uri": (
            "wandb-run-file://entity/project/run-one/"
            "media/eval_tables/images/eval/"
            f"{digest[: _eval_table_media_ces._DIGEST_PATH_LENGTH]}.png"
        ),
    }
    assert image._run is None
    assert image._path == str(path)


def test_committed_artifact_image_preserves_artifact_ref_url(
    run_factory,
    tmp_path,
    monkeypatch,
):
    run = run_factory("run-one")
    image = wandb.Image(_png(tmp_path))
    artifact_uri = "wandb-artifact://abc123/media/images/image.png"
    monkeypatch.setattr(image, "_get_artifact_entry_ref_url", lambda: artifact_uri)

    prepared = _eval_table_media_ces.prepare_image(image, run, _IMAGE_FIELD)

    assert prepared.value["uri"] == artifact_uri
    assert image._run is None
    run._publish_file.assert_not_called()


def test_external_reference_artifact_image_is_null_by_default(
    run_factory,
    tmp_path,
    monkeypatch,
):
    run = run_factory("run-one")
    image = _image_from_external_reference_artifact(tmp_path, monkeypatch)
    warning = MagicMock()
    monkeypatch.setattr(wandb, "termwarn", warning)
    writer = _eval_table_writer_ces.CESEvalTableWriter()
    writer.bind_to_run(run, "eval", 0)

    prepared = writer._build_write_payloads(_image_write_input(image))

    assert prepared.row_batches[0][0]["input"]["image"] is None
    assert prepared.dataset_fields == [
        {
            "source": "input",
            "name": "image",
            "value_type": "json",
            "extension_type": "wandb-image",
            "extension_schema_version": 1,
        }
    ]
    warning.assert_called_once()


def test_external_reference_artifact_image_raises_in_raise_mode(
    run_factory,
    tmp_path,
    monkeypatch,
):
    run = run_factory("run-one")
    image = _image_from_external_reference_artifact(tmp_path, monkeypatch)
    writer = _eval_table_writer_ces.CESEvalTableWriter(unsupported_media_mode="raise")
    writer.bind_to_run(run, "eval", 0)

    with pytest.raises(TypeError, match="external reference artifacts"):
        writer._build_write_payloads(_image_write_input(image))


def test_artifact_rehydrated_image_mask_registers_parent_class_labels(
    run_factory,
    artifact_image_factory,
):
    run = run_factory("run-one")
    class_labels = {1: "truth region: Coat", 2: "prediction region: Trouser"}
    image, artifact_uri = artifact_image_factory(
        name="image",
        class_labels=class_labels,
        mask_keys=("predictions",),
    )

    prepared = _eval_table_media_ces.prepare_image(image, run, _IMAGE_FIELD)

    assert prepared.value["uri"] == artifact_uri
    mask = prepared.value["masks"]["predictions"]
    assert mask["uri"].startswith("wandb-run-file://entity/project/run-one/")
    assert run._add_singleton.call_args == call(
        "mask/class_labels",
        "eval/inputs/image_wandb_delimeter_predictions",
        class_labels,
    )
    assert "mask_data" not in mask


def test_artifact_rehydrated_image_boxes_register_parent_class_labels(
    run_factory,
    artifact_image_factory,
):
    run = run_factory("run-one")
    class_labels = {1: "truth region: Coat", 2: "prediction region: Trouser"}
    image, artifact_uri = artifact_image_factory(
        name="image",
        class_labels=class_labels,
        boxes={
            "predictions": [
                {
                    "position": {
                        "minX": 0.1,
                        "minY": 0.2,
                        "maxX": 0.3,
                        "maxY": 0.4,
                    },
                    "class_id": 2,
                }
            ]
        },
    )

    prepared = _eval_table_media_ces.prepare_image(image, run, _IMAGE_FIELD)

    assert prepared.value["uri"] == artifact_uri
    boxes = prepared.value["boxes"]["predictions"]
    assert boxes["uri"].startswith("wandb-run-file://entity/project/run-one/")
    assert run._add_singleton.call_args == call(
        "bounding_box/class_labels",
        "eval/inputs/image_wandb_delimeter_predictions",
        {2: class_labels[2]},
    )


def test_image_with_masks_and_boxes_uses_run_file_uris(run_factory, tmp_path):
    np = pytest.importorskip("numpy")
    run = run_factory("run-one")
    image = wandb.Image(
        _png(tmp_path),
        boxes={
            "predictions": {
                "box_data": [
                    {
                        "position": {
                            "minX": 0.1,
                            "minY": 0.2,
                            "maxX": 0.3,
                            "maxY": 0.4,
                        },
                        "class_id": 1,
                    }
                ],
                "class_labels": {1: "cat"},
            }
        },
        masks={
            "predictions": {
                "mask_data": np.zeros((2, 2), dtype=np.uint8),
                "class_labels": {0: "background"},
            }
        },
    )
    box_media = image._boxes["predictions"]
    mask_media = image._masks["predictions"]
    image_path = image._path
    box_path = box_media._path
    mask_path = mask_media._path

    prepared = _eval_table_media_ces.prepare_image(image, run, _IMAGE_FIELD)

    box = prepared.value["boxes"]["predictions"]
    mask = prepared.value["masks"]["predictions"]
    assert box["uri"].startswith(
        "wandb-run-file://entity/project/run-one/media/eval_tables/metadata/boxes2D/eval/"
    )
    assert "path" not in box
    assert mask["uri"].startswith(
        "wandb-run-file://entity/project/run-one/media/eval_tables/images/mask/eval/"
    )
    assert "path" not in mask
    assert run._publish_file.call_count == 3
    assert run._add_singleton.call_count == 2
    assert image._run is None
    assert image._path == image_path
    assert box_media._run is None
    assert box_media._path == box_path
    assert mask_media._run is None
    assert mask_media._path == mask_path


def test_image_columns_register_distinct_overlay_class_labels(
    run_factory,
    mock_ces_client,
    tmp_path,
    artifact_image_factory,
):
    np = pytest.importorskip("numpy")
    run = run_factory("run-one")
    local_image = wandb.Image(
        _png(tmp_path, "local.png"),
        boxes={
            "comparison": {
                "box_data": [
                    {
                        "position": {
                            "minX": 0.1,
                            "minY": 0.2,
                            "maxX": 0.3,
                            "maxY": 0.4,
                        },
                        "class_id": 1,
                    }
                ],
                "class_labels": {1: "local"},
            }
        },
        masks={
            "comparison": {
                "mask_data": np.ones((2, 2), dtype=np.uint8),
                "class_labels": {1: "local"},
            }
        },
    )

    artifact_image, _ = artifact_image_factory(
        name="artifact",
        class_labels={2: "artifact"},
        boxes={
            "comparison": [
                {
                    "position": {
                        "minX": 0.2,
                        "minY": 0.3,
                        "maxX": 0.4,
                        "maxY": 0.5,
                    },
                    "class_id": 2,
                }
            ]
        },
        mask_keys=("comparison",),
    )
    table = wandb.EvalTable(
        columns=["local_image", "artifact_image"],
        data=[[local_image, artifact_image]],
        input_columns=["local_image", "artifact_image"],
        backend="ces",
    )

    run.log({"eval": table})

    assert run._add_singleton.call_args_list == [
        call(
            "bounding_box/class_labels",
            "eval/inputs/local_image_wandb_delimeter_comparison",
            {1: "local"},
        ),
        call(
            "mask/class_labels",
            "eval/inputs/local_image_wandb_delimeter_comparison",
            {1: "local"},
        ),
        call(
            "bounding_box/class_labels",
            "eval/inputs/artifact_image_wandb_delimeter_comparison",
            {2: "artifact"},
        ),
        call(
            "mask/class_labels",
            "eval/inputs/artifact_image_wandb_delimeter_comparison",
            {2: "artifact"},
        ),
    ]


def test_cell_at_size_limit_becomes_null(run_factory, tmp_path, monkeypatch):
    run = run_factory("run-one")
    first = wandb.Image(_png(tmp_path, "first.png"), caption="caption")
    first_result = _eval_table_media_ces.prepare_image(first, run, _IMAGE_FIELD)
    second_path = tmp_path / "second.png"
    second_path.write_bytes(Path(first._path).read_bytes())
    second = wandb.Image(second_path, caption="caption")
    monkeypatch.setattr(
        _eval_table_media_ces,
        "CES_MAX_CELL_BYTES",
        first_result.encoded_size,
    )

    result = _eval_table_media_ces.prepare_image(second, run, _IMAGE_FIELD)

    assert result.encoded_size == first_result.encoded_size
    assert result.value is None
    assert result.oversized


def test_eval_table_writes_image_extension_to_ces(
    run_factory,
    mock_ces_client,
    tmp_path,
):
    run = run_factory("run-one")
    image = wandb.Image(_png(tmp_path))
    table = wandb.EvalTable(
        columns=["image"],
        data=[[image]],
        input_columns=["image"],
        backend="ces",
    )

    run.log({"eval": table})

    mock_ces_client.eval_tables.create_columns.assert_called_once_with(
        "evaluation-1",
        namespace="wandb",
        scope_ref="scope-ref",
        dataset_fields=[
            {
                "source": "input",
                "name": "image",
                "value_type": "json",
                "extension_type": "wandb-image",
                "extension_schema_version": 1,
            }
        ],
        scorers=[],
        idempotency_key=ANY,
    )


def test_image_score_is_rejected_as_non_primitive(run_factory, tmp_path):
    run = run_factory("run-one")
    image = wandb.Image(_png(tmp_path))
    writer = _eval_table_writer_ces.CESEvalTableWriter()
    writer.bind_to_run(run, "eval", 0)
    value = _eval_table_writer.EvalTableWriteInput(
        name="eval",
        rows=[
            _eval_table_writer.EvalTableWriteRow(
                inputs={"value": "x"},
                outputs=None,
                scores={"image": image},
            )
        ],
        column_keys={"value": "value", "image": "image"},
        ncols=2,
        log_mode="IMMUTABLE",
    )

    with pytest.raises(UsageError, match="only primitive values"):
        writer._build_write_payloads(value)
