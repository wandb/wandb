import os
from typing import Any, ClassVar, Dict, List, Optional, Type, TYPE_CHECKING, Union

import six
from wandb import util

from . import _dtypes
from ._private import MEDIA_TMP
from .base_types.Media import Media

if TYPE_CHECKING:  # pragma: no cover
    from wandb.apis.public import Artifact as PublicArtifact

    from ..wandb_artifacts import Artifact as LocalArtifact
    from ..wandb_run import Run as LocalRun

    # TODO: make these richer
    ModelObjType = Any
    ModelFilePathType = str
    ModelDirPathType = str
    ModelPathType = Union[ModelFilePathType, ModelDirPathType]
    ModelType = Union[ModelPathType, ModelObjType]

    RegisteredSerializerMapType = Dict[str, "_IModelSerializer"]


class _SerializerRegistry(object):
    _registered_serializers: ClassVar[Optional[RegisteredSerializerMapType]] = None

    @staticmethod
    def register_serializer(serializer: "_IModelSerializer") -> None:
        serializers = _SerializerRegistry.registered_serializers()
        if serializer.serializer_id in serializers:
            raise ValueError(
                "Cannot add serializer with id {}, already exists".format(
                    serializer.serializer_id
                )
            )
        serializers[serializer.serializer_id] = serializer

    @staticmethod
    def registered_serializers() -> RegisteredSerializerMapType:
        if _SerializerRegistry._registered_serializers is None:
            _SerializerRegistry._registered_serializers = {}
        return _SerializerRegistry._registered_serializers

    @staticmethod
    def load_serializer(serializer_id: str) -> "_IModelSerializer":
        selected_serializer = _SerializerRegistry.registered_serializers()[
            serializer_id
        ]
        if selected_serializer is None:
            raise ValueError(f"Serializer {serializer_id} not registered")
        return selected_serializer

    @staticmethod
    def handles_model_or_path(
        serializer: "_IModelSerializer", model_or_path: ModelType,
    ) -> bool:
        possible = False
        if _is_path(model_or_path):
            possible = serializer.can_load_path(model_or_path)
        else:
            possible = serializer.can_save_model(model_or_path)
        return possible

    @staticmethod
    def find_suitable_serializer(
        model_or_path: ModelType,
    ) -> Optional["_IModelSerializer"]:
        serializers = _SerializerRegistry.registered_serializers()
        for key in serializers:
            serializer = serializers[key]
            if _SerializerRegistry.handles_model_or_path(serializer, model_or_path):
                return serializer
        return None


class SavedModel(Media):
    _log_type: ClassVar[str] = "saved-model"

    _serializer: "_IModelSerializer"
    _model_spec: "_ModelSpec"
    _model_obj: Optional[ModelObjType]
    _path: Optional[str]

    def __init__(
        self,
        model_or_path: ModelType,
        serializer_id: Optional[str] = None,
        _model_spec: Optional["_ModelSpec"] = None,
    ) -> None:
        super(SavedModel, self).__init__()
        if serializer_id is None:
            selected_serializer = _SerializerRegistry.find_suitable_serializer(
                model_or_path
            )
            if selected_serializer is None:
                raise ValueError("No suitable serializer found for model")
        else:
            selected_serializer = _SerializerRegistry.load_serializer(serializer_id)
            if not _SerializerRegistry.handles_model_or_path(
                selected_serializer, model_or_path
            ):
                raise ValueError(
                    f"Serializer {selected_serializer} cannot load or save selected model"
                )

        self._serializer = selected_serializer
        if _is_path(model_or_path):
            # TODO: make media support a directory path
            self._set_file(model_or_path)
        else:
            tmp_path = os.path.join(MEDIA_TMP.name, str(util.generate_id()))
            selected_serializer.save_model(model_or_path, tmp_path)
            self._model_obj = model_or_path
            # TODO: make media support a directory path (this is going to be non-trivial)
            self._set_file(tmp_path, is_tmp=True)

        if _model_spec is None:
            self._model_spec = self._serializer.get_model_specs(self.raw_model)

    @property
    def raw_model(self) -> ModelObjType:
        if self._model_obj is None:
            if self._path is None:
                raise ValueError("No model to load")
            self._model_obj = self._serializer.load_path(self._path)
        return self._model_obj

    def to_json(self, run_or_artifact: Union["LocalRun", "LocalArtifact"]) -> dict:
        json_obj = super(SavedModel, self).to_json(run_or_artifact)
        json_obj["serializer_id"] = self._serializer.serializer_id
        json_obj["model_spec"] = self._model_spec.to_json()
        return json_obj

    @classmethod
    def from_json(
        cls: Type["SavedModel"], json_obj: dict, source_artifact: "PublicArtifact"
    ) -> "SavedModel":
        # TODO: make download support directories
        return cls(
            source_artifact.get_path(json_obj["path"]).download(),
            json_obj["serializer_id"],
            json_obj["model_spec"],
        )


def _is_path(model_or_path: ModelType) -> bool:
    return isinstance(model_or_path, six.string_types) and os.path.exists(model_or_path)


class _ModelSpec(object):
    # TODO: Figure out the best way to generalize these attributes
    _inputs: Optional[Dict[str, List[int]]]
    _outputs: Optional[Dict[str, List[int]]]

    def __init__(
        self,
        inputs: Optional[Dict[str, List[int]]],
        outputs: Optional[Dict[str, List[int]]],
    ) -> None:
        self._inputs = inputs
        self._outputs = outputs

    def to_json(self) -> Dict[str, Any]:
        return {
            "_inputs": self._inputs,
            "_outputs": self._outputs,
        }


class _IModelSerializer(object):
    serializer_id: str

    @staticmethod
    def can_load_path(dir_or_file_path: ModelPathType) -> bool:
        raise NotImplementedError()

    @staticmethod
    def load_path(dir_or_file_path: ModelPathType) -> ModelObjType:
        raise NotImplementedError()

    @staticmethod
    def can_save_model(obj: ModelObjType) -> bool:
        raise NotImplementedError()

    @staticmethod
    def save_model(obj: ModelObjType, dir_path: ModelDirPathType) -> None:
        raise NotImplementedError()

    @staticmethod
    def get_model_specs(obj: ModelObjType) -> _ModelSpec:
        raise NotImplementedError()


# TODO: Implement the basic serializers


# Note: Thinking about how the type system works now, I think
# we will be able to write a cleaner interface that allows the
# media type to encode the type of the data. However, it might be
# worth waiting for Shawn to finish his Python Weave implementation.
class _SavedModelType(_dtypes.Type):
    name = "saved-model"
    types = [SavedModel]

    def __init__(self, serializer_id: str, model_spec: Dict[str, Any]) -> None:
        self.params.update({"serializer_id": serializer_id, "model_spec": model_spec})

    @classmethod
    def from_obj(cls, py_obj: Optional[Any] = None) -> "_SavedModelType":
        if not isinstance(py_obj, SavedModel):
            raise TypeError("py_obj must be a SavedModel")
        else:
            return cls(py_obj._serializer.serializer_id, py_obj._model_spec.to_json())


_dtypes.TypeRegistry.add(_SavedModelType)
