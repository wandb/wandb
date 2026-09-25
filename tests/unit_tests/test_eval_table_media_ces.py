from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import ANY, MagicMock, call

import pytest
import wandb
from PIL import Image as PILImage
from wandb.errors import UsageError
from wandb.sdk.data_types.eval_table import _media_ces, _writer, _writer_ces

pytestmark = pytest.mark.usefixtures("coreweave_evaluations_module")


@pytest.fixture
def coreweave_evaluations_module(monkeypatch):
    client_module = ModuleType("coreweave_evaluations")
    client_module.__path__ = []
    client_module.Client = MagicMock

    types_module = ModuleType("coreweave_evaluations.types")
    types_module.__path__ = []
    audio_module = ModuleType("coreweave_evaluations.types.wandb_audio_v1_param")
    audio_module.WandbAudioV1Param = dict
    image_module = ModuleType("coreweave_evaluations.types.wandb_image_v1_param")
    image_module.WandbImageV1Param = dict
    video_module = ModuleType("coreweave_evaluations.types.wandb_video_v1_param")
    video_module.WandbVideoV1Param = dict

    monkeypatch.setitem(sys.modules, "coreweave_evaluations", client_module)
    monkeypatch.setitem(sys.modules, "coreweave_evaluations.types", types_module)
    monkeypatch.setitem(
        sys.modules,
        "coreweave_evaluations.types.wandb_audio_v1_param",
        audio_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "coreweave_evaluations.types.wandb_image_v1_param",
        image_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "coreweave_evaluations.types.wandb_video_v1_param",
        video_module,
    )
    return client_module


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
def mock_ces_client(monkeypatch, coreweave_evaluations_module):
    client = MagicMock()
    client.__enter__.return_value = client
    client.eval_tables.create.return_value = SimpleNamespace(
        dataset_id="dataset-1",
        evaluation_id="evaluation-1",
    )
    client.eval_tables.versions.create.return_value = SimpleNamespace(
        dataset_version_id="dataset-version-1",
        evaluation_version_id="evaluation-version-1",
    )
    monkeypatch.setenv("CES_BASE_URL", "https://evaluations.example.test")
    monkeypatch.setattr(coreweave_evaluations_module, "Client", MagicMock)
    monkeypatch.setattr(
        _writer_ces.CESWriter,
        "_resolve_scope_context",
        lambda self, bound: _writer_ces._CESScopeContext(
            scope_id="scope-ref",
            api_key=None,
            access_token="token",
        ),
    )
    monkeypatch.setattr(
        _writer_ces.CESWriter,
        "_create_client",
        lambda self, client_type, base_url, scope: client,
    )
    return client


def _png(tmp_path, name="image.png", color=(10, 20, 30)):
    path = tmp_path / name
    PILImage.new("RGB", (2, 2), color=color).save(path)
    return path


def _image_write_rows(image):
    return [
        _writer.WriteRow(
            inputs={"image": image},
            output=None,
            scores={},
        )
    ]


def _box(class_id=1):
    return {
        "position": {"minX": 0.1, "minY": 0.2, "maxX": 0.3, "maxY": 0.4},
        "class_id": class_id,
    }


def _box_overlay(class_labels, *, class_id=1):
    return {"box_data": [_box(class_id)], "class_labels": class_labels}


def _mask_overlay(class_labels, *, fill=1):
    np = pytest.importorskip("numpy")
    return {
        "mask_data": np.full((2, 2), fill, dtype=np.uint8),
        "class_labels": class_labels,
    }


def _audio_write_rows(audio):
    return [
        _writer.WriteRow(
            inputs={"audio": audio},
            output=None,
            scores={},
        )
    ]


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


def _write_bytes(tmp_path, name, contents):
    path = tmp_path / name
    path.write_bytes(contents)
    return path


def _audio_or_video_with_local_file(tmp_path, media_kind, *, caption=None):
    if media_kind == "audio":
        path = _write_bytes(tmp_path, "sound.wav", b"audio contents")
        return wandb.Audio(path, caption=caption), path
    if media_kind == "video":
        path = _write_bytes(tmp_path, "clip.mp4", b"video contents")
        video = wandb.Video(path, caption=caption)
        video._width = 640
        video._height = 480
        return video, path
    raise ValueError(f"Unknown media kind: {media_kind}")


_IMAGE_FIELD = _media_ces.EvalTableMediaField(
    eval_table_key="eval",
    source="inputs",
    column_name="image",
)


def _image_from_external_reference_artifact(
    tmp_path,
    monkeypatch,
    **image_kwargs,
):
    image = wandb.Image(_png(tmp_path), **image_kwargs)
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

    assert (
        _media_ces._committed_artifact_ref_url(
            image,
            parent_extension_type="wandb-image",
        )
        == artifact_ref_url
    )


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

    uri = _media_ces._ensure_eval_table_run_file(
        image,
        run,
        "eval/key",
        parent_extension_type="wandb-image",
    )

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


def test_repeated_media_content_is_placed_once(run_factory, tmp_path):
    run = run_factory("run-one")
    path = _png(tmp_path)
    first = wandb.Image(path)
    second = wandb.Image(path)

    _media_ces._ensure_eval_table_run_file(
        first,
        run,
        "eval",
        parent_extension_type="wandb-image",
    )
    _media_ces._ensure_eval_table_run_file(
        second,
        run,
        "eval",
        parent_extension_type="wandb-image",
    )

    assert second._run is run
    assert second._path == first._path
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

    working_image = _media_ces._media_for_run(image, run)
    uri = _media_ces._ensure_eval_table_run_file(
        working_image,
        run,
        "eval",
        parent_extension_type="wandb-image",
    )

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
    uri = _media_ces._ensure_eval_table_run_file(
        working_image,
        destination_run,
        "eval",
        parent_extension_type="wandb-image",
    )

    assert image._run is source_run
    assert image._path == original_path
    assert working_image is not image
    assert uri.startswith("wandb-run-file://entity/project/destination-run/")
    destination_run._publish_file.assert_called_once()


def test_ces_eval_table_supports_registered_media_types():
    assert _media_ces.SUPPORTED_WANDB_MEDIA_TYPES == (
        wandb.Image,
        wandb.Audio,
        wandb.Video,
    )


def test_prepare_image_creates_ces_extension_value(run_factory, tmp_path):
    run = run_factory("run-one")
    path = _png(tmp_path)
    image = wandb.Image(path, grouping=7)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    prepared = _media_ces.prepare_image(image, run, _IMAGE_FIELD)

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
            f"{digest[: _media_ces._DIGEST_PATH_LENGTH]}.png"
        ),
    }
    assert image._run is None
    assert image._path == str(path)


@pytest.mark.parametrize(
    ("media_kind", "caption", "subdir", "extension_type", "wb_media_type", "extra"),
    [
        pytest.param(
            "audio",
            "a sound",
            "audio",
            "wandb-audio",
            "audio-file",
            {},
            id="audio",
        ),
        pytest.param(
            "video",
            "a clip",
            "videos",
            "wandb-video",
            "video-file",
            {"width": 640, "height": 480},
            id="video",
        ),
    ],
)
def test_prepare_audio_and_video_creates_ces_extension_value(
    media_kind,
    caption,
    subdir,
    extension_type,
    wb_media_type,
    extra,
    run_factory,
    tmp_path,
):
    run = run_factory("run-one")
    media, path = _audio_or_video_with_local_file(tmp_path, media_kind, caption=caption)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    prepared = _media_ces.prepare_media(
        media,
        run,
        _media_ces.EvalTableMediaField(
            eval_table_key="eval/key",
            source="inputs",
            column_name="media",
        ),
    )

    expected_path = os.path.join(
        "media",
        "eval_tables",
        subdir,
        "eval",
        "key",
        f"{digest[: _media_ces._DIGEST_PATH_LENGTH]}{path.suffix}",
    )
    assert prepared.value == {
        "caption": caption,
        "sha256": digest,
        "size": path.stat().st_size,
        "extension_type": extension_type,
        "schema_version": 1,
        "wb_media_type": wb_media_type,
        "uri": "wandb-run-file://entity/project/run-one/"
        + expected_path.replace(os.sep, "/"),
        **extra,
    }
    assert media._run is None
    assert media._path == str(path)


def test_committed_artifact_image_preserves_artifact_ref_url(
    run_factory,
    tmp_path,
    monkeypatch,
):
    run = run_factory("run-one")
    image = wandb.Image(_png(tmp_path))
    artifact_uri = "wandb-artifact://abc123/media/images/image.png"
    monkeypatch.setattr(image, "_get_artifact_entry_ref_url", lambda: artifact_uri)

    prepared = _media_ces.prepare_image(image, run, _IMAGE_FIELD)

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
    writer = _writer_ces.CESWriter()
    writer.bind_to_run(run, "eval", 0)

    prepared = writer._build_write_payloads(
        name="eval",
        rows=_image_write_rows(image),
    )

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
    writer = _writer_ces.CESWriter(unsupported_media_mode="raise")
    writer.bind_to_run(run, "eval", 0)

    with pytest.raises(TypeError, match="external reference artifacts"):
        writer._build_write_payloads(
            name="eval",
            rows=_image_write_rows(image),
        )


def test_external_reference_audio_is_null_by_default(run_factory, monkeypatch):
    run = run_factory("run-one")
    audio = wandb.Audio("s3://bucket/sound.wav")
    warning = MagicMock()
    monkeypatch.setattr(wandb, "termwarn", warning)
    writer = _writer_ces.CESWriter()
    writer.bind_to_run(run, "eval", 0)

    prepared = writer._build_write_payloads(
        name="eval",
        rows=_audio_write_rows(audio),
    )

    assert prepared.row_batches[0][0]["input"]["audio"] is None
    assert prepared.dataset_fields == [
        {
            "source": "input",
            "name": "audio",
            "value_type": "json",
            "extension_type": "wandb-audio",
            "extension_schema_version": 1,
        }
    ]
    warning.assert_called_once()


def test_external_reference_audio_raises_in_raise_mode(run_factory):
    run = run_factory("run-one")
    audio = wandb.Audio("s3://bucket/sound.wav")
    writer = _writer_ces.CESWriter(unsupported_media_mode="raise")
    writer.bind_to_run(run, "eval", 0)

    with pytest.raises(TypeError, match="reference external storage"):
        writer._build_write_payloads(
            name="eval",
            rows=_audio_write_rows(audio),
        )


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

    prepared = _media_ces.prepare_image(image, run, _IMAGE_FIELD)

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
        boxes={"predictions": [_box(2)]},
    )

    prepared = _media_ces.prepare_image(image, run, _IMAGE_FIELD)

    assert prepared.value["uri"] == artifact_uri
    boxes = prepared.value["boxes"]["predictions"]
    assert boxes["uri"].startswith("wandb-run-file://entity/project/run-one/")
    assert run._add_singleton.call_args == call(
        "bounding_box/class_labels",
        "eval/inputs/image_wandb_delimeter_predictions",
        {2: class_labels[2]},
    )


def test_image_with_masks_and_boxes_uses_run_file_uris(run_factory, tmp_path):
    run = run_factory("run-one")
    image = wandb.Image(
        _png(tmp_path),
        boxes={"predictions": _box_overlay({1: "cat"})},
        masks={"predictions": _mask_overlay({0: "background"}, fill=0)},
    )
    box_media = image._boxes["predictions"]
    mask_media = image._masks["predictions"]
    image_path = image._path
    box_path = box_media._path
    mask_path = mask_media._path

    prepared = _media_ces.prepare_image(image, run, _IMAGE_FIELD)

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


def test_image_overlay_keys_register_distinct_class_labels(
    run_factory,
    mock_ces_client,
    tmp_path,
):
    run = run_factory("run-one")
    run._add_singleton = MagicMock(
        wraps=wandb.Run._add_singleton.__get__(run, wandb.Run)
    )
    image = wandb.Image(
        _png(tmp_path),
        boxes={
            "ground_truth": _box_overlay({1: "truth"}),
            "predictions": _box_overlay({1: "prediction"}),
        },
        masks={
            "ground_truth": _mask_overlay({1: "truth"}),
            "predictions": _mask_overlay({1: "prediction"}),
        },
    )
    table = wandb.EvalTable(
        columns=["image"],
        data=[[image]],
        input_columns=["image"],
        backend="ces",
    )

    run.log({"eval": table})

    wandb_config = run._config["_wandb"]
    assert wandb_config["bounding_box/class_labels"] == {
        "eval/inputs/image_wandb_delimeter_ground_truth": {
            "type": "bounding_box/class_labels",
            "key": "eval/inputs/image_wandb_delimeter_ground_truth",
            "value": {1: "truth"},
        },
        "eval/inputs/image_wandb_delimeter_predictions": {
            "type": "bounding_box/class_labels",
            "key": "eval/inputs/image_wandb_delimeter_predictions",
            "value": {1: "prediction"},
        },
    }
    assert wandb_config["mask/class_labels"] == {
        "eval/inputs/image_wandb_delimeter_ground_truth": {
            "type": "mask/class_labels",
            "key": "eval/inputs/image_wandb_delimeter_ground_truth",
            "value": {1: "truth"},
        },
        "eval/inputs/image_wandb_delimeter_predictions": {
            "type": "mask/class_labels",
            "key": "eval/inputs/image_wandb_delimeter_predictions",
            "value": {1: "prediction"},
        },
    }


def test_image_rows_merge_overlay_class_labels(
    run_factory,
    mock_ces_client,
    tmp_path,
):
    run = run_factory("run-one")
    run._add_singleton = MagicMock(
        wraps=wandb.Run._add_singleton.__get__(run, wandb.Run)
    )

    def image(name, class_labels):
        return wandb.Image(
            _png(tmp_path, name),
            boxes={"comparison": _box_overlay(class_labels)},
            masks={"comparison": _mask_overlay(class_labels)},
        )

    table = wandb.EvalTable(
        columns=["image"],
        data=[
            [image("first.png", {1: "A", 2: "B"})],
            [image("second.png", {2: "different B", 3: "C"})],
        ],
        input_columns=["image"],
        backend="ces",
    )

    run.log({"eval": table})

    singleton_key = "eval/inputs/image_wandb_delimeter_comparison"
    expected_labels = {1: "A", 2: "B", 3: "C"}
    wandb_config = run._config["_wandb"]
    assert wandb_config["bounding_box/class_labels"][singleton_key]["value"] == (
        expected_labels
    )
    assert wandb_config["mask/class_labels"][singleton_key]["value"] == expected_labels
    assert run._add_singleton.call_args_list == [
        call("bounding_box/class_labels", singleton_key, expected_labels),
        call("mask/class_labels", singleton_key, expected_labels),
    ]


def test_image_overlay_class_labels_merge_with_resumed_string_ids(
    run_factory,
    mock_ces_client,
    tmp_path,
):
    run = run_factory("run-one")
    singleton_key = "eval/inputs/image_wandb_delimeter_comparison"
    # Resumed runs load config through JSON, so class IDs come back as strings.
    wandb.Run._add_singleton(
        run, "bounding_box/class_labels", singleton_key, {"1": "established"}
    )
    run._add_singleton = MagicMock(
        wraps=wandb.Run._add_singleton.__get__(run, wandb.Run)
    )
    image = wandb.Image(
        _png(tmp_path),
        boxes={"comparison": _box_overlay({1: "new", 2: "B"})},
    )
    table = wandb.EvalTable(
        columns=["image"],
        data=[[image]],
        input_columns=["image"],
        backend="ces",
    )

    run.log({"eval": table})

    assert run._add_singleton.call_args_list == [
        call(
            "bounding_box/class_labels",
            singleton_key,
            {"1": "established", 2: "B"},
        ),
    ]


def test_image_columns_register_distinct_overlay_class_labels(
    run_factory,
    mock_ces_client,
    tmp_path,
    artifact_image_factory,
):
    run = run_factory("run-one")
    local_image = wandb.Image(
        _png(tmp_path, "local.png"),
        boxes={"comparison": _box_overlay({1: "local"})},
        masks={"comparison": _mask_overlay({1: "local"})},
    )

    artifact_image, _ = artifact_image_factory(
        name="artifact",
        class_labels={2: "artifact"},
        boxes={"comparison": [_box(2)]},
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


def test_external_reference_artifact_image_overlays_are_null_by_default(
    run_factory,
    tmp_path,
    monkeypatch,
):
    run = run_factory("run-one")
    image = _image_from_external_reference_artifact(
        tmp_path,
        monkeypatch,
        boxes={"predictions": {"box_data": [], "class_labels": {}}},
    )
    warning = MagicMock()
    monkeypatch.setattr(wandb, "termwarn", warning)
    writer = _writer_ces.CESWriter()
    writer.bind_to_run(run, "eval", 0)

    prepared = writer._build_write_payloads(
        name="eval",
        rows=_image_write_rows(image),
    )

    assert prepared.row_batches[0][0]["input"]["image"] is None
    assert prepared.dataset_fields[0]["extension_type"] == "wandb-image"
    warning.assert_called_once()


def test_external_reference_artifact_image_overlays_raise_in_raise_mode(
    run_factory,
    tmp_path,
    monkeypatch,
):
    run = run_factory("run-one")
    image = _image_from_external_reference_artifact(
        tmp_path,
        monkeypatch,
        boxes={"predictions": {"box_data": [], "class_labels": {}}},
    )
    writer = _writer_ces.CESWriter(unsupported_media_mode="raise")
    writer.bind_to_run(run, "eval", 0)

    with pytest.raises(TypeError, match="external reference artifacts"):
        writer._build_write_payloads(
            name="eval",
            rows=_image_write_rows(image),
        )


def test_cell_at_size_limit_becomes_null(run_factory, tmp_path, monkeypatch):
    run = run_factory("run-one")
    first = wandb.Image(_png(tmp_path, "first.png"), caption="caption")
    first_result = _media_ces.prepare_image(first, run, _IMAGE_FIELD)
    second_path = tmp_path / "second.png"
    second_path.write_bytes(Path(first._path).read_bytes())
    second = wandb.Image(second_path, caption="caption")
    monkeypatch.setattr(
        _media_ces,
        "CES_MAX_CELL_BYTES",
        first_result.encoded_size,
    )

    result = _media_ces.prepare_image(second, run, _IMAGE_FIELD)

    assert result.encoded_size == first_result.encoded_size
    assert result.value is None
    assert result.oversized


def test_eval_table_writes_supported_media_extensions_to_ces(
    run_factory,
    mock_ces_client,
    tmp_path,
):
    run = run_factory("run-one")
    image = wandb.Image(_png(tmp_path))
    audio, _ = _audio_or_video_with_local_file(tmp_path, "audio")
    video, _ = _audio_or_video_with_local_file(tmp_path, "video")
    table = wandb.EvalTable(
        columns=["image", "audio", "video"],
        data=[[image, audio, video]],
        input_columns=["image", "audio", "video"],
        backend="ces",
    )

    run.log({"eval": table})

    mock_ces_client.eval_tables.columns.create.assert_called_once_with(
        "evaluation-1",
        namespace="wandb",
        scope_id="scope-ref",
        dataset_fields=[
            {
                "source": "input",
                "name": "image",
                "value_type": "json",
                "extension_type": "wandb-image",
                "extension_schema_version": 1,
            },
            {
                "source": "input",
                "name": "audio",
                "value_type": "json",
                "extension_type": "wandb-audio",
                "extension_schema_version": 1,
            },
            {
                "source": "input",
                "name": "video",
                "value_type": "json",
                "extension_type": "wandb-video",
                "extension_schema_version": 1,
            },
        ],
        scorers=[],
        idempotency_key=ANY,
    )
    inputs = mock_ces_client.eval_tables.rows.add.call_args.kwargs["rows"][0]["input"]
    assert inputs["image"]["extension_type"] == "wandb-image"
    assert inputs["image"]["format"] == "png"
    assert inputs["audio"]["extension_type"] == "wandb-audio"
    assert inputs["video"]["extension_type"] == "wandb-video"


def test_image_score_is_rejected_as_non_primitive(run_factory, tmp_path):
    run = run_factory("run-one")
    image = wandb.Image(_png(tmp_path))
    writer = _writer_ces.CESWriter()
    writer.bind_to_run(run, "eval", 0)
    rows = [
        _writer.WriteRow(
            inputs={"value": "x"},
            output=None,
            scores={"image": image},
        )
    ]

    with pytest.raises(UsageError, match="only primitive values"):
        writer._build_write_payloads(name="eval", rows=rows)
