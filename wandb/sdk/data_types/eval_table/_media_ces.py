"""Prepare W&B media values for CES-backed EvalTable writes.

This module converts supported media into CES extension values backed by durable
artifact or run-file references. Supported implementations preserve these source
semantics:

* Newly created media is bound to the active run and stored as a run file.
* Media already bound to the active run reuses its run file. Media bound to a
  different run is copied before binding, leaving the original object unchanged.
* Artifact-backed media preserves its committed W&B artifact URI. External
  reference artifacts are unsupported because CES cannot authenticate to them.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypeVar
from urllib.parse import quote

from wandb import util
from wandb.errors import UsageError
from wandb.sdk.data_types.audio import Audio
from wandb.sdk.data_types.base_types.media import Media
from wandb.sdk.data_types.helper_types.bounding_boxes_2d import BoundingBoxes2D
from wandb.sdk.data_types.helper_types.image_mask import ImageMask
from wandb.sdk.data_types.image import Image
from wandb.sdk.data_types.video import Video
from wandb.sdk.lib import filesystem
from wandb.sdk.lib.paths import LogicalPath

if TYPE_CHECKING:
    from coreweave_evaluations.types.wandb_audio_v1_param import WandbAudioV1Param
    from coreweave_evaluations.types.wandb_image_v1_param import WandbImageV1Param
    from coreweave_evaluations.types.wandb_video_v1_param import WandbVideoV1Param

    from wandb.sdk.data_types.helper_types.classes import Classes
    from wandb.sdk.wandb_run import Run

    _CESMediaExtensionValue = WandbImageV1Param | WandbAudioV1Param | WandbVideoV1Param


# Stays under the 3.5 MiB ClickHouse single-row insert limit that Weave adopted
# after larger rows failed in production (wandb/weave#2353, wandb/weave#5448).
CES_MAX_CELL_BYTES = 3_500_000
CESExtensionType = Literal["wandb-image", "wandb-audio", "wandb-video"]
_MediaFieldSource = Literal["inputs", "outputs"]
_DIGEST_PATH_LENGTH = 30
_MediaT = TypeVar("_MediaT", bound=Media)


@dataclass(frozen=True)
class PreparedMediaCell:
    """A CES extension value and its encoded-size metadata for one media cell.

    Media implementations set `value` to `None` when the encoded extension value
    reaches `CES_MAX_CELL_BYTES` while retaining its type and size metadata.
    """

    value: _CESMediaExtensionValue | None
    extension_type: CESExtensionType
    extension_schema_version: int
    encoded_size: int
    oversized: bool


@dataclass(frozen=True)
class EvalTableMediaField:
    """Identify media so overlay labels use the same config keys as run media."""

    eval_table_key: str
    source: _MediaFieldSource
    column_name: str

    def singleton_key(self, overlay_key: str) -> str:
        media_key = f"{self.eval_table_key}/{self.source}/{self.column_name}"
        return f"{media_key}_wandb_delimeter_{overlay_key}"


def _add_missing_class_labels(
    labels: dict[int | str, str],
    new_labels: dict[int | str, str],
) -> None:
    """Adds entries from new_labels whose class IDs are missing from labels.

    IDs are compared as strings because resumed runs load config through JSON,
    which turns integer class IDs into string keys.
    """
    known_ids = {str(class_id) for class_id in labels}
    for class_id, name in new_labels.items():
        if str(class_id) not in known_ids:
            labels[class_id] = name
            known_ids.add(str(class_id))


class ClassLabelAccumulator:
    def __init__(self) -> None:
        self._labels: dict[
            tuple[str, str],
            dict[int | str, str],
        ] = {}

    def add(
        self,
        media: Media,
        field: EvalTableMediaField,
        class_labels: dict[int | str, str] | None,
    ) -> None:
        if class_labels is None:
            return

        if isinstance(media, BoundingBoxes2D):
            singleton_type = "bounding_box/class_labels"
        elif isinstance(media, ImageMask):
            singleton_type = "mask/class_labels"
        else:
            return

        key = (singleton_type, field.singleton_key(media._key))
        _add_missing_class_labels(self._labels.setdefault(key, {}), class_labels)

    def flush(self, run: Run) -> None:
        for (singleton_type, singleton_key), class_labels in self._labels.items():
            existing_entry = (
                run._config["_wandb"].get(singleton_type, {}).get(singleton_key)
            )
            existing_labels = (
                existing_entry.get("value")
                if isinstance(existing_entry, dict)
                else None
            )
            merged_labels = (
                dict(existing_labels) if isinstance(existing_labels, dict) else {}
            )
            # Preserve established names on ID collisions, matching Table schemas.
            _add_missing_class_labels(merged_labels, class_labels)
            run._add_singleton(singleton_type, singleton_key, merged_labels)


class UnsupportedMediaVariantError(TypeError):
    """Raised when EvalTable supports a media type but not its backing data."""

    def __init__(
        self,
        message: str,
        *,
        stub_warning: str,
        extension_type: CESExtensionType,
    ) -> None:
        super().__init__(message)
        self.stub_warning = stub_warning
        self.extension_type = extension_type


_MEDIA_EXTENSION_TYPES: dict[type[Media], CESExtensionType] = {
    Image: "wandb-image",
    Audio: "wandb-audio",
    Video: "wandb-video",
}
SUPPORTED_WANDB_MEDIA_TYPES: tuple[type[Media], ...] = tuple(_MEDIA_EXTENSION_TYPES)


def _media_extension_type(media: Media) -> CESExtensionType | None:
    for media_type, extension_type in _MEDIA_EXTENSION_TYPES.items():
        if isinstance(media, media_type):
            return extension_type
    return None


def is_supported_wandb_media(value: Any) -> bool:
    return isinstance(value, SUPPORTED_WANDB_MEDIA_TYPES)


def prepare_media(
    media: Media,
    run: Run,
    field: EvalTableMediaField,
    class_label_accumulator: ClassLabelAccumulator | None = None,
) -> PreparedMediaCell:
    """Prepare supported media for one EvalTable cell in the active run."""
    if isinstance(media, Image):
        return prepare_image(media, run, field, class_label_accumulator)

    extension_type = _media_extension_type(media)
    if extension_type is None:
        raise UsageError(
            f"CES EvalTable does not support media type {type(media).__name__!r}."
        )
    return _prepare_file_media(media, run, field, extension_type)


def prepare_image(
    image: Image,
    run: Run,
    field: EvalTableMediaField,
    class_label_accumulator: ClassLabelAccumulator | None = None,
) -> PreparedMediaCell:
    accumulated_labels = class_label_accumulator or ClassLabelAccumulator()
    working_image = _image_for_run(image, run)
    if _committed_artifact_ref_url(working_image) is None:
        _ensure_eval_table_run_file(working_image, run, field.eval_table_key)

    for overlay in _image_overlays(working_image):
        _ensure_eval_table_run_file(overlay, run, field.eval_table_key)
        accumulated_labels.add(
            overlay,
            field,
            _overlay_class_labels(overlay, working_image._classes),
        )

    if class_label_accumulator is None:
        accumulated_labels.flush(run)

    image_json = working_image.to_json(run)
    extension_value = _image_ces_extension_value(image_json, run)
    _rewrite_image_overlay_references(extension_value, run)
    return _prepared_media_cell(extension_value, extension_type="wandb-image")


def _prepare_file_media(
    media: Media,
    run: Run,
    field: EvalTableMediaField,
    extension_type: CESExtensionType,
) -> PreparedMediaCell:
    working_media = _media_for_run(media, run)
    if _committed_artifact_ref_url(working_media) is None:
        _ensure_eval_table_run_file(working_media, run, field.eval_table_key)

    media_json = working_media.to_json(run)
    if isinstance(working_media, Audio):
        extension_value = _audio_ces_extension_value(media_json, run)
    elif isinstance(working_media, Video):
        extension_value = _video_ces_extension_value(media_json, run)
    else:
        raise TypeError(
            f"Unsupported EvalTable file media type {type(working_media).__name__!r}."
        )
    return _prepared_media_cell(extension_value, extension_type=extension_type)


def _prepared_media_cell(
    extension_value: _CESMediaExtensionValue,
    *,
    extension_type: CESExtensionType,
) -> PreparedMediaCell:
    encoded_size = len(_encode_json(extension_value))
    oversized = encoded_size >= CES_MAX_CELL_BYTES
    return PreparedMediaCell(
        value=None if oversized else extension_value,
        extension_type=extension_type,
        extension_schema_version=1,
        encoded_size=encoded_size,
        oversized=oversized,
    )


def _media_for_run(media: _MediaT, run: Run) -> _MediaT:
    if media._run is run:
        return media
    return _unbound_copy(media)


def _image_for_run(image: Image, run: Run) -> Image:
    cloned = _media_for_run(image, run)
    if cloned is image:
        cloned = copy.copy(image)
    cloned._boxes = (
        {key: _media_for_run(box, run) for key, box in image._boxes.items()}
        if image._boxes
        else None
    )
    cloned._masks = (
        {key: _media_for_run(mask, run) for key, mask in image._masks.items()}
        if image._masks
        else None
    )
    return cloned


def _unbound_copy(media: _MediaT) -> _MediaT:
    cloned = copy.copy(media)
    cloned._run = None
    # The original retains ownership of temporary files, so preparation copies them.
    cloned._is_tmp = False
    return cloned


def _image_overlays(image: Image) -> list[Media]:
    overlays: list[Media] = []
    if image._boxes:
        overlays.extend(image._boxes.values())
    if image._masks:
        overlays.extend(image._masks.values())
    return overlays


def _committed_artifact_ref_url(media: Media) -> str | None:
    ref_url = media._get_artifact_entry_ref_url()
    if util._is_artifact_string(ref_url):
        _check_external_reference_artifact(media)
        return ref_url
    return None


def _check_external_reference_artifact(media: Media) -> None:
    source = media._artifact_source
    if source is None:
        return

    # A W&B artifact URI can wrap external storage that the EvalTable service
    # cannot access.
    artifact = source.artifact
    entry_names = []
    if source.name is not None:
        entry_names.append(media.with_suffix(source.name))
    if media._path is not None:
        media_entry_name = artifact._local_path_to_name(media._path)
        if media_entry_name is not None:
            entry_names.append(media_entry_name)

    for entry_name in entry_names:
        entry = artifact.get_entry(entry_name)
        is_external_reference = (
            entry.ref is not None and not entry._is_artifact_reference()
        )
        if is_external_reference:
            type_name = type(media).__name__
            extension_type = _media_extension_type(media)
            raise UnsupportedMediaVariantError(
                f"EvalTable does not support wandb.{type_name} values backed by "
                "external reference artifacts. Pass unsupported_media_mode='stub' "
                "to log null instead.",
                stub_warning=(
                    f"wandb.{type_name} values backed by external reference artifacts "
                    "are not supported by EvalTable. They will be logged as null."
                ),
                extension_type=extension_type or "wandb-image",
            )


# Only unbound media may enter the EvalTable run-file namespace. Callers preserve
# committed artifact references and copy cross-run media before binding.
def _ensure_eval_table_run_file(
    media: Media,
    run: Run,
    eval_table_key: str,
) -> str:
    if media._run is run:
        return _run_file_uri(run, _logical_run_file_path(media, run))

    if media._run is not None:
        raise UsageError(
            f"Cannot rebind {type(media).__name__} from a different run in place."
        )

    _check_external_reference_artifact(media)

    if media.path_is_reference(media._path):
        raise ValueError(
            f"{type(media).__name__} media created by a reference to external "
            "storage cannot currently be added to a run"
        )

    if not media.file_is_set():
        raise UsageError(
            f"Cannot log {type(media).__name__} in an EvalTable without a file."
        )

    assert media._path is not None
    assert media._sha256 is not None
    extension = media._extension
    if extension is None:
        _, extension = os.path.splitext(os.path.basename(media._path))

    relative_subdir = os.path.relpath(media.get_media_subdir(), "media")
    safe_eval_table_key = util.make_file_path_upload_safe(str(eval_table_key))
    directory = os.path.join(
        "media", "eval_tables", relative_subdir, safe_eval_table_key
    )
    # A 120-bit prefix has about a 1 in 2.7 quintillion collision chance among
    # one billion files.
    logical_path = os.path.join(
        directory,
        f"{media._sha256[:_DIGEST_PATH_LENGTH]}{extension}",
    )
    _place_media_file_in_run(media, run, logical_path)
    return _run_file_uri(run, logical_path)


# Mirrors the file placement in `Media.bind_to_run`, which only supports its own
# key/step/id naming, so EvalTables can keep content-addressed paths for dedupe.
def _place_media_file_in_run(media: Media, run: Run, logical_path: str) -> None:
    assert media._path is not None
    new_path = os.path.join(run.dir, logical_path)
    # Media repeated across rows shares one content-addressed file, so copy and
    # publish it once.
    if not media._is_tmp and os.path.exists(new_path):
        media._path = new_path
        media._run = run
        return

    filesystem.mkdir_exists_ok(os.path.dirname(new_path))

    if media._is_tmp:
        shutil.move(media._path, new_path)
        media._is_tmp = False
    elif run._settings.allow_media_symlink:
        filesystem.link_or_copy(
            run._settings,
            pathlib.Path(media._path).resolve(),
            pathlib.Path(new_path),
        )
    else:
        shutil.copy(media._path, new_path)

    media._path = new_path
    media._run = run
    run._publish_file(logical_path)


def _logical_run_file_path(media: Media, run: Run) -> LogicalPath:
    if media._path is None:
        raise UsageError(f"Bound {type(media).__name__} has no run file path.")
    return LogicalPath(os.path.relpath(media._path, run.dir))


def _run_file_uri(run: Run, logical_path: str) -> str:
    if not run.entity or not run.project or not run.id:
        raise UsageError("EvalTable media requires an entity, project, and run ID.")
    components = [run.entity, run.project, run.id]
    path_components = LogicalPath(logical_path).parts
    encoded = "/".join(
        quote(str(part), safe="") for part in (*components, *path_components)
    )
    return f"wandb-run-file://{encoded}"


def _rewrite_image_overlay_references(
    extension_value: WandbImageV1Param,
    run: Run,
) -> None:
    """Replace local overlay paths with durable CES references."""
    for collection in ("boxes", "masks"):
        if collection in extension_value:
            extension_value[collection] = {
                key: _referenced_media_value(value, run)
                for key, value in extension_value[collection].items()
            }


def _remaining_media_fields(
    media_json: dict[str, Any],
    *,
    consumed_fields: set[str],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in media_json.items()
        if key
        not in {
            "_type",
            "path",
            "artifact_path",
            "_latest_artifact_path",
            "extension_type",
            "schema_version",
            "uri",
            "wb_media_type",
            *consumed_fields,
        }
    }


def _image_ces_extension_value(
    media_json: dict[str, Any],
    run: Run,
) -> WandbImageV1Param:
    # Keep the generated CES client optional until CES media is serialized.
    from coreweave_evaluations.types.wandb_image_v1_param import WandbImageV1Param

    return WandbImageV1Param(
        extension_type="wandb-image",
        format=media_json["format"],
        schema_version=1,
        sha256=media_json["sha256"],
        size=media_json["size"],
        uri=_uri_from_media_json(media_json, run),
        wb_media_type="image-file",
        **_remaining_media_fields(
            media_json,
            consumed_fields={"format", "sha256", "size"},
        ),
    )


def _audio_ces_extension_value(
    media_json: dict[str, Any],
    run: Run,
) -> WandbAudioV1Param:
    from coreweave_evaluations.types.wandb_audio_v1_param import WandbAudioV1Param

    return WandbAudioV1Param(
        extension_type="wandb-audio",
        schema_version=1,
        sha256=media_json["sha256"],
        size=media_json["size"],
        uri=_uri_from_media_json(media_json, run),
        wb_media_type="audio-file",
        **_remaining_media_fields(
            media_json,
            consumed_fields={"sha256", "size"},
        ),
    )


def _video_ces_extension_value(
    media_json: dict[str, Any],
    run: Run,
) -> WandbVideoV1Param:
    from coreweave_evaluations.types.wandb_video_v1_param import WandbVideoV1Param

    return WandbVideoV1Param(
        extension_type="wandb-video",
        schema_version=1,
        sha256=media_json["sha256"],
        size=media_json["size"],
        uri=_uri_from_media_json(media_json, run),
        wb_media_type="video-file",
        **_remaining_media_fields(
            media_json,
            consumed_fields={"sha256", "size"},
        ),
    )


def _overlay_class_labels(
    media: Media | None,
    image_classes: Classes | None,
) -> dict[int | str, str] | None:
    if isinstance(media, ImageMask):
        # Path-backed and artifact-rehydrated masks never set _val, so image.py
        # guards it with hasattr for the same reason.
        # TODO: Read class labels through an ImageMask accessor instead.
        value = getattr(media, "_val", None)
        if isinstance(value, dict) and isinstance(value.get("class_labels"), dict):
            return value["class_labels"]
        return _image_class_labels(image_classes)
    if isinstance(media, BoundingBoxes2D):
        return _box_class_labels(media, image_classes)
    return None


def _image_class_labels(
    image_classes: Classes | None,
) -> dict[int | str, str] | None:
    if image_classes is None:
        return None
    return {
        class_item["id"]: class_item["name"] for class_item in image_classes._class_set
    }


def _box_class_labels(
    media: BoundingBoxes2D,
    image_classes: Classes | None,
) -> dict[int | str, str] | None:
    class_labels = media._class_labels
    labels_are_generated = all(
        name == f"class_{class_id}" for class_id, name in class_labels.items()
    )
    if not labels_are_generated or image_classes is None:
        return class_labels

    parent_labels = _image_class_labels(image_classes) or {}
    return {
        class_id: parent_labels.get(class_id, name)
        for class_id, name in class_labels.items()
    }


def _referenced_media_value(
    media_json: dict[str, Any],
    run: Run,
) -> dict[str, Any]:
    value = {
        key: value
        for key, value in media_json.items()
        if key not in {"path", "artifact_path", "_latest_artifact_path"}
    }
    value["uri"] = _uri_from_media_json(media_json, run)
    return value


def _uri_from_media_json(value: dict[str, Any], run: Run) -> str:
    artifact_path = value.get("artifact_path")
    if util._is_artifact_string(artifact_path):
        return artifact_path
    path = value.get("path")
    if not isinstance(path, str):
        raise UsageError("EvalTable media JSON has no durable file reference.")
    return _run_file_uri(run, path)


def _encode_json(value: Any) -> bytes:
    """Encode JSON exactly as the CES client does for body-size checks."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
