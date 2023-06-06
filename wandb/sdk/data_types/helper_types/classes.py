import os
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence, Type, Union

from .. import _dtypes
from ..base_types.media import Media

if TYPE_CHECKING:  # pragma: no cover
    from wandb.sdk.artifacts.artifact import Artifact

    from ...wandb_run import Run as LocalRun


class Classes(Media):
    _log_type = "classes"

    _class_set: Sequence[dict]

    def __init__(self, class_set: Sequence[dict]) -> None:
        """Classes is holds class metadata intended to be used in concert with other objects when visualizing artifacts.

        Args:
            class_set (list): list of dicts in the form of {"id":int|str, "name":str}
        """
        super().__init__()
        for class_obj in class_set:
            assert "id" in class_obj and "name" in class_obj
        self._class_set = class_set

    @classmethod
    def from_json(
        cls: Type["Classes"],
        json_obj: dict,
        source_artifact: Optional["Artifact"],
    ) -> "Classes":
        return cls(json_obj.get("class_set"))  # type: ignore

    def to_json(self, run_or_artifact: Optional[Union["LocalRun", "Artifact"]]) -> dict:
        json_obj = {}
        # This is a bit of a hack to allow _ClassesIdType to
        # be able to operate fully without an artifact in play.
        # In all other cases, artifact should be a true artifact.
        if run_or_artifact is not None:
            json_obj = super().to_json(run_or_artifact)
        json_obj["_type"] = Classes._log_type
        json_obj["class_set"] = self._class_set
        return json_obj

    def get_type(self) -> "_ClassesIdType":
        return _ClassesIdType(self)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Classes):
            return self._class_set == other._class_set
        else:
            return False


class _ClassesIdType(_dtypes.Type):
    name = "classesId"
    legacy_names = ["wandb.Classes_id"]
    types = [Classes]

    def __init__(
        self,
        classes_obj: Optional[Classes] = None,
        valid_ids: Optional["_dtypes.UnionType"] = None,
    ):
        if valid_ids is None:
            valid_ids = _dtypes.UnionType()
        elif isinstance(valid_ids, list):
            valid_ids = _dtypes.UnionType(
                [_dtypes.ConstType(item) for item in valid_ids]
            )
        elif isinstance(valid_ids, _dtypes.UnionType):
            valid_ids = valid_ids
        else:
            raise TypeError("valid_ids must be None, list, or UnionType")

        if classes_obj is None:
            classes_obj = Classes(
                [
                    {"id": _id.params["val"], "name": str(_id.params["val"])}
                    for _id in valid_ids.params["allowed_types"]
                ]
            )
        elif not isinstance(classes_obj, Classes):
            raise TypeError("valid_ids must be None, or instance of Classes")
        else:
            valid_ids = _dtypes.UnionType(
                [
                    _dtypes.ConstType(class_obj["id"])
                    for class_obj in classes_obj._class_set
                ]
            )

        self.wb_classes_obj_ref = classes_obj
        self.params.update({"valid_ids": valid_ids})

    def assign(self, py_obj: Optional[Any] = None) -> "_dtypes.Type":
        return self.assign_type(_dtypes.ConstType(py_obj))

    def assign_type(self, wb_type: "_dtypes.Type") -> "_dtypes.Type":
        valid_ids = self.params["valid_ids"].assign_type(wb_type)
        if not isinstance(valid_ids, _dtypes.InvalidType):
            return self

        return _dtypes.InvalidType()

    @classmethod
    def from_obj(cls, py_obj: Optional[Any] = None) -> "_dtypes.Type":
        return cls(py_obj)

    def to_json(self, artifact: Optional["Artifact"] = None) -> Dict[str, Any]:
        cl_dict = super().to_json(artifact)
        # TODO (tss): Refactor this block with the similar one in wandb.Image.
        # This is a bit of a smell that the classes object does not follow
        # the same file-pattern as other media types.
        if artifact is not None:
            class_name = os.path.join("media", "cls")
            classes_entry = artifact.add(self.wb_classes_obj_ref, class_name)
            cl_dict["params"]["classes_obj"] = {
                "type": "classes-file",
                "path": classes_entry.path,
                "digest": classes_entry.digest,  # is this needed really?
            }
        else:
            cl_dict["params"]["classes_obj"] = self.wb_classes_obj_ref.to_json(artifact)
        return cl_dict

    @classmethod
    def from_json(
        cls,
        json_dict: Dict[str, Any],
        artifact: Optional["Artifact"] = None,
    ) -> "_dtypes.Type":
        classes_obj = None
        if (
            json_dict.get("params", {}).get("classes_obj", {}).get("type")
            == "classes-file"
        ):
            if artifact is not None:
                classes_obj = artifact.get(
                    json_dict.get("params", {}).get("classes_obj", {}).get("path")
                )
                assert classes_obj is None or isinstance(classes_obj, Classes)
            else:
                raise RuntimeError("Expected artifact to be non-null.")
        else:
            classes_obj = Classes.from_json(
                json_dict["params"]["classes_obj"], artifact
            )

        return cls(classes_obj)


_dtypes.TypeRegistry.add(_ClassesIdType)
