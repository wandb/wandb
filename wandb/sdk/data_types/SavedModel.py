import os
from typing import Any, ClassVar, Dict, List, Optional, Type, TYPE_CHECKING, Union

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

    RegisteredAdaptersMapType = Dict[str, Type["_IModelAdapter"]]


class _ModelAdapterRegistry(object):
    _registered_adapters: ClassVar[Optional[RegisteredAdaptersMapType]] = None

    @staticmethod
    def register_adapter(adapter: Type["_IModelAdapter"]) -> None:
        adapters = _ModelAdapterRegistry.registered_adapters()
        if adapter.adapter_id in adapters:
            raise ValueError(
                "Cannot add adapter with id {}, already exists".format(
                    adapter.adapter_id
                )
            )
        adapters[adapter.adapter_id] = adapter

    @staticmethod
    def registered_adapters() -> RegisteredAdaptersMapType:
        if _ModelAdapterRegistry._registered_adapters is None:
            _ModelAdapterRegistry._registered_adapters = {}
        return _ModelAdapterRegistry._registered_adapters

    @staticmethod
    def load_adapter(adapter_id: str) -> Type["_IModelAdapter"]:
        selected_adapter = _ModelAdapterRegistry.registered_adapters()[
            adapter_id
        ]
        if selected_adapter is None:
            raise ValueError(f"adapter {adapter_id} not registered")
        return selected_adapter

    @staticmethod
    def handles_model_or_path(
        adapter: Type["_IModelAdapter"], model_or_path: ModelType,
    ) -> bool:
        possible = False
        if _is_path(model_or_path):
            possible = adapter.can_load_path(model_or_path)
        else:
            possible = adapter.can_adapt_model(model_or_path)
        return possible

    @staticmethod
    def find_suitable_adapter(
        model_or_path: ModelType,
    ) -> Optional[Type["_IModelAdapter"]]:
        adapters = _ModelAdapterRegistry.registered_adapters()
        for key in adapters:
            adapter = adapters[key]
            if _ModelAdapterRegistry.handles_model_or_path(adapter, model_or_path):
                return adapter
        return None


class SavedModel(Media):
    _log_type: ClassVar[str] = "saved-model"

    _adapter_cls: Type["_IModelAdapter"]
    _adapter: Optional["_IModelAdapter"]
    _path: Optional[str]

    def __init__(
        self,
        model_or_path: ModelType,
        adapter_id: Optional[str] = None,
    ) -> None:
        super(SavedModel, self).__init__()
        if adapter_id is None:
            selected_adapter_cls = _ModelAdapterRegistry.find_suitable_adapter(
                model_or_path
            )
            if selected_adapter_cls is None:
                raise ValueError("No suitable adapter found for model")
        else:
            selected_adapter_cls = _ModelAdapterRegistry.load_adapter(adapter_id)
            if not _ModelAdapterRegistry.handles_model_or_path(
                selected_adapter_cls, model_or_path
            ):
                raise ValueError(
                    f"adapter {selected_adapter_cls} cannot load or save selected model"
                )

        self._adapter_cls = selected_adapter_cls
        if _is_path(model_or_path):
            # TODO: make media support a directory path
            self._set_file(model_or_path)
        else:
            # We immediately write the file(s) in case the user modifies the model
            # after creating the SavedModel (ie. continues training)
            self._adapter = selected_adapter_cls(model_or_path)
            tmp_path = os.path.join(MEDIA_TMP.name, str(util.generate_id()))
            self.adapter.save_model(tmp_path)
            # TODO: make media support a directory path (this is going to be non-trivial)
            self._set_file(tmp_path, is_tmp=True)

    @property
    def adapter(self) -> "_IModelAdapter":
        if self._adapter is None:
            self._adapter = self._adapter_cls.init_from_path(self._path)
        return self._adapter

    @property
    def raw(self) -> ModelObjType:
        return self.adapter.raw()

    def to_json(self, run_or_artifact: Union["LocalRun", "LocalArtifact"]) -> dict:
        json_obj = super(SavedModel, self).to_json(run_or_artifact)
        json_obj["adapter_id"] = self.adapter.adapter_id
        json_obj["model_spec"] = self.adapter.model_spec.to_json()
        return json_obj

    @classmethod
    def from_json(
        cls: Type["SavedModel"], json_obj: dict, source_artifact: "PublicArtifact"
    ) -> "SavedModel":
        # TODO: make download support directories
        return cls(
            source_artifact.get_path(json_obj["path"]).download(),
            json_obj["adapter_id"],
            # purposely ignoring the model spec - it can be re-calculated from the model
        )


def _is_path(model_or_path: ModelType) -> bool:
    return isinstance(model_or_path, str) and os.path.exists(model_or_path)


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

from typing import TypeVar, Generic

ModelObjectType = TypeVar('ModelObjectType')
class _IModelAdapter(Generic[ModelObjectType]):
    adapter_id: str
    _internal_model: ModelObjType

    def __init__(self, model: ModelObjectType) -> None:
        self._internal_model = model

    @classmethod
    def init_from_path(cls: Type["_IModelAdapter"], dir_or_file_path: ModelPathType) -> "_IModelAdapter":
        raise NotImplementedError()

    @staticmethod
    def can_load_path(dir_or_file_path: ModelPathType) -> bool:
        raise NotImplementedError()

    @staticmethod
    def can_adapt_model(obj: Any) -> bool:
        raise NotImplementedError()

    def save_model(self, dir_path: ModelDirPathType) -> None:
        raise NotImplementedError()

    def model_spec(self) -> _ModelSpec:
        raise NotImplementedError()

    def raw(self) -> ModelObjectType:
        return self._internal_model


# TODO: Implement the basic adapters


# Note: Thinking about how the type system works now, I think
# we will be able to write a cleaner interface that allows the
# media type to encode the type of the data. However, it might be
# worth waiting for Shawn to finish his Python Weave implementation.
class _SavedModelType(_dtypes.Type):
    name = "saved-model"
    types = [SavedModel]

    def __init__(self, adapter_id: str, model_spec: Dict[str, Any]) -> None:
        self.params.update({"adapter_id": adapter_id, "model_spec": model_spec})

    @classmethod
    def from_obj(cls, py_obj: Optional[Any] = None) -> "_SavedModelType":
        if not isinstance(py_obj, SavedModel):
            raise TypeError("py_obj must be a SavedModel")
        else:
            return cls(py_obj._adapter.adapter_id, py_obj._model_spec.to_json())


_dtypes.TypeRegistry.add(_SavedModelType)
