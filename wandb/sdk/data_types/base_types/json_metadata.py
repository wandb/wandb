import codecs
import os
from typing import TYPE_CHECKING, Type, Union

from wandb import util
from wandb.sdk.lib import runid

from .._private import MEDIA_TMP
from .media import Media

if TYPE_CHECKING:  # pragma: no cover
    from wandb.sdk.artifacts.artifact import Artifact

    from ...wandb_run import Run as LocalRun


# Allows encoding of arbitrary JSON structures
# as a file
#
# This class should be used as an abstract class
# extended to have validation methods


class JSONMetadata(Media):
    """JSONMetadata is a type for encoding arbitrary metadata as files."""

    def __init__(self, val: dict) -> None:
        super().__init__()

        self.validate(val)
        self._val = val

        ext = "." + self.type_name() + ".json"
        tmp_path = os.path.join(MEDIA_TMP.name, runid.generate_id() + ext)
        with codecs.open(tmp_path, "w", encoding="utf-8") as fp:
            util.json_dump_uncompressed(self._val, fp)
        self._set_file(tmp_path, is_tmp=True, extension=ext)

    @classmethod
    def get_media_subdir(cls: Type["JSONMetadata"]) -> str:
        return os.path.join("media", "metadata", cls.type_name())

    def to_json(self, run_or_artifact: Union["LocalRun", "Artifact"]) -> dict:
        json_dict = super().to_json(run_or_artifact)
        json_dict["_type"] = self.type_name()

        return json_dict

    # These methods should be overridden in the child class
    @classmethod
    def type_name(cls) -> str:
        return "metadata"

    def validate(self, val: dict) -> bool:
        return True
