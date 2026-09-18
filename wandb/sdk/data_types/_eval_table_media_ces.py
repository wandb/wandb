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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast
from urllib.parse import quote

from wandb import util
from wandb.errors import UsageError
from wandb.sdk.data_types.audio import Audio
from wandb.sdk.data_types.base_types.media import Media
from wandb.sdk.data_types.helper_types.bounding_boxes_2d import BoundingBoxes2D
from wandb.sdk.data_types.helper_types.image_mask import ImageMask
from wandb.sdk.data_types.image import Image
from wandb.sdk.data_types.video import Video
from wandb.sdk.lib.paths import LogicalPath

if TYPE_CHECKING:
    from coreweave_evaluations.types.wandb_audio_v1_param import WandbAudioV1Param
    from coreweave_evaluations.types.wandb_image_v1_param import WandbImageV1Param
    from coreweave_evaluations.types.wandb_video_v1_param import WandbVideoV1Param

    from wandb.sdk.data_types.helper_types.classes import Classes
    from wandb.sdk.wandb_run import Run

    _CESMediaExtensionValue = WandbImageV1Param | WandbAudioV1Param | WandbVideoV1Param


CES_MAX_CELL_BYTES = 3_500_000
_CESExtensionType = Literal["wandb-image", "wandb-audio", "wandb-video"]
_WBMediaType = Literal["image-file", "audio-file", "video-file"]
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
    extension_type: _CESExtensionType
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


class _UnsupportedMediaVariantError(TypeError):
    """Raised when EvalTable supports a media type but not its backing data."""

    def __init__(
        self,
        message: str,
        *,
        stub_warning: str,
        extension_type: _CESExtensionType,
    ) -> None:
        super().__init__(message)
        self.stub_warning = stub_warning
        self.extension_type = extension_type


@dataclass(frozen=True)
class _MediaSpec:
    """Describe the CES extension metadata for one supported media type."""

    media_type: type[Media]
    extension_type: _CESExtensionType
    wb_media_type: _WBMediaType


_MEDIA_SPECS = (
    _MediaSpec(Image, "wandb-image", "image-file"),
    _MediaSpec(Audio, "wandb-audio", "audio-file"),
    _MediaSpec(Video, "wandb-video", "video-file"),
)
SUPPORTED_WANDB_MEDIA_TYPES: tuple[type[Media], ...] = tuple(
    spec.media_type for spec in _MEDIA_SPECS
)


def _media_spec(media: Media) -> _MediaSpec | None:
    return next(
        (spec for spec in _MEDIA_SPECS if isinstance(media, spec.media_type)),
        None,
    )


def is_supported_wandb_media(value: Any) -> bool:
    return isinstance(value, SUPPORTED_WANDB_MEDIA_TYPES)


def prepare_media(
    media: Media,
    run: Run,
    field: EvalTableMediaField,
) -> PreparedMediaCell:
    """Prepare supported media for one EvalTable cell in the active run."""

    if isinstance(media, Image):
        return prepare_image(media, run, field)

    spec = _media_spec(media)
    if spec is None:
        raise UsageError(
            f"CES EvalTable does not support media type {type(media).__name__!r}."
        )
    return _prepare_file_media(media, run, field, spec)


def prepare_image(
    image: Image,
    run: Run,
    field: EvalTableMediaField,
) -> PreparedMediaCell:
    working_image = _image_for_run(image, run)
    if _committed_artifact_ref_url(working_image) is None:
        _bind_eval_table_media_to_run(working_image, run, field.eval_table_key)

    for overlay in _image_overlays(working_image):
        _bind_eval_table_media_to_run(overlay, run, field.eval_table_key)
        _register_class_labels(
            overlay,
            run,
            field,
            _overlay_class_labels(overlay, working_image._classes),
        )

    image_json = working_image.to_json(run)
    extension_value = _image_ces_extension_value(image_json, run)
    _rewrite_image_overlay_references(extension_value, run)
    return _prepared_media_cell(extension_value, extension_type="wandb-image")


def _prepare_file_media(
    media: Media,
    run: Run,
    field: EvalTableMediaField,
    spec: _MediaSpec,
) -> PreparedMediaCell:
    working_media = _media_for_run(media, run)
    if _committed_artifact_ref_url(working_media) is None:
        _bind_eval_table_media_to_run(working_media, run, field.eval_table_key)

    media_json = working_media.to_json(run)
    extension_value = _base_ces_extension_value(
        media_json,
        run,
        extension_type=spec.extension_type,
        wb_media_type=spec.wb_media_type,
    )
    return _prepared_media_cell(extension_value, extension_type=spec.extension_type)


def _prepared_media_cell(
    extension_value: _CESMediaExtensionValue,
    *,
    extension_type: _CESExtensionType,
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


def _media_for_run(media: _MediaT, _run: Run) -> _MediaT:
    return _unbound_copy(media)


def _image_for_run(image: Image, run: Run) -> Image:
    cloned = _media_for_run(image, run)
    cloned._boxes = (
        {key: _unbound_copy(box) for key, box in image._boxes.items()}
        if image._boxes
        else None
    )
    cloned._masks = (
        {key: _unbound_copy(mask) for key, mask in image._masks.items()}
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
            spec = _media_spec(media)
            raise _UnsupportedMediaVariantError(
                f"EvalTable does not support wandb.{type_name} values backed by "
                "external reference artifacts. Pass unsupported_media_mode='stub' "
                "to log null instead.",
                stub_warning=(
                    f"wandb.{type_name} values backed by external reference artifacts "
                    "are not supported by EvalTable. They will be logged as null."
                ),
                extension_type=(
                    spec.extension_type if spec is not None else "wandb-image"
                ),
            )


# Only unbound media may enter the EvalTable run-file namespace. Callers preserve
# committed artifact references and copy cross-run media before binding.
def _bind_eval_table_media_to_run(
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
    media._bind_to_run_path(run, logical_path)
    return _run_file_uri(run, logical_path)


def _register_class_labels(
    media: Media,
    run: Run,
    field: EvalTableMediaField,
    class_labels: dict[int | str, str] | None,
) -> None:
    if class_labels is None:
        return

    singleton_key = field.singleton_key(media._key)
    if isinstance(media, BoundingBoxes2D):
        run._add_singleton(
            "bounding_box/class_labels",
            singleton_key,
            class_labels,
        )
    elif isinstance(media, ImageMask):
        run._add_singleton(
            "mask/class_labels",
            singleton_key,
            class_labels,
        )


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


def _base_ces_extension_value(
    media_json: dict[str, Any],
    run: Run,
    *,
    extension_type: _CESExtensionType,
    wb_media_type: _WBMediaType,
) -> _CESMediaExtensionValue:
    extension_value = {
        key: value
        for key, value in media_json.items()
        if key not in {"_type", "path", "artifact_path", "_latest_artifact_path"}
    }
    extension_value.update(
        {
            "extension_type": extension_type,
            "schema_version": 1,
            "wb_media_type": wb_media_type,
            "uri": _uri_from_media_json(media_json, run),
        }
    )
    return cast("_CESMediaExtensionValue", extension_value)


def _image_ces_extension_value(
    media_json: dict[str, Any],
    run: Run,
) -> WandbImageV1Param:
    return cast(
        "WandbImageV1Param",
        _base_ces_extension_value(
            media_json,
            run,
            extension_type="wandb-image",
            wb_media_type="image-file",
        ),
    )


def _overlay_class_labels(
    media: Media | None,
    image_classes: Classes | None,
) -> dict[int | str, str] | None:
    if isinstance(media, ImageMask):
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
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
