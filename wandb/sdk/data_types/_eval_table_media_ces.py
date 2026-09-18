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
from wandb.sdk.data_types.base_types.media import Media
from wandb.sdk.data_types.image import Image
from wandb.sdk.lib.paths import LogicalPath

if TYPE_CHECKING:
    from coreweave_evaluations.types.wandb_image_v1_param import WandbImageV1Param

    from wandb.sdk.wandb_run import Run

    _CESMediaExtensionValue = WandbImageV1Param


CES_MAX_CELL_BYTES = 3_500_000
_CESExtensionType = Literal["wandb-image"]
_DIGEST_PATH_LENGTH = 30
_MediaT = TypeVar("_MediaT", bound=Media)
SUPPORTED_WANDB_MEDIA_TYPES: tuple[type[Media], ...] = (Image,)


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


def is_supported_wandb_media(value: Any) -> bool:
    return isinstance(value, SUPPORTED_WANDB_MEDIA_TYPES)


def prepare_media(
    media: Media,
    run: Run,
    eval_table_key: str,
) -> PreparedMediaCell:
    """Prepare supported media for one EvalTable cell in the active run."""

    if isinstance(media, Image):
        return prepare_image(media, run, eval_table_key)
    raise UsageError(
        f"CES EvalTable does not support media type {type(media).__name__!r}."
    )


def prepare_image(image: Image, run: Run, eval_table_key: str) -> PreparedMediaCell:
    if image._boxes or image._masks:
        raise _UnsupportedMediaVariantError(
            "EvalTable does not support wandb.Image masks or boxes yet. Pass "
            "unsupported_media_mode='stub' to log null instead.",
            stub_warning=(
                "wandb.Image values with masks or boxes are not supported by "
                "EvalTable yet. They will be logged as null."
            ),
            extension_type="wandb-image",
        )

    working_image = _media_for_run(image, run)
    if _committed_artifact_ref_url(working_image) is None:
        _bind_eval_table_media_to_run(working_image, run, eval_table_key)

    image_json = working_image.to_json(run)
    extension_value = _image_ces_extension_value(image_json, run)
    encoded_size = len(_encode_json(extension_value))
    oversized = encoded_size >= CES_MAX_CELL_BYTES
    return PreparedMediaCell(
        value=None if oversized else extension_value,
        extension_type="wandb-image",
        extension_schema_version=1,
        encoded_size=encoded_size,
        oversized=oversized,
    )


def _media_for_run(media: _MediaT, _run: Run) -> _MediaT:
    return _unbound_copy(media)


def _unbound_copy(media: _MediaT) -> _MediaT:
    cloned = copy.copy(media)
    cloned._run = None
    # The original retains ownership of temporary files, so preparation copies them.
    cloned._is_tmp = False
    return cloned


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
            raise _UnsupportedMediaVariantError(
                "EvalTable does not support wandb.Image values backed by "
                "external reference artifacts. Pass unsupported_media_mode='stub' "
                "to log null instead.",
                stub_warning=(
                    "wandb.Image values backed by external reference artifacts "
                    "are not supported by EvalTable. They will be logged as null."
                ),
                extension_type="wandb-image",
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
def _image_ces_extension_value(
    image_json: dict[str, Any],
    run: Run,
) -> WandbImageV1Param:
    uri = _uri_from_media_json(image_json, run)
    extension_value = {
        key: value
        for key, value in image_json.items()
        if key not in {"_type", "path", "artifact_path", "_latest_artifact_path"}
    }
    extension_value.update(
        {
            "extension_type": "wandb-image",
            "schema_version": 1,
            "wb_media_type": "image-file",
            "uri": uri,
        }
    )
    return cast("WandbImageV1Param", extension_value)


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
