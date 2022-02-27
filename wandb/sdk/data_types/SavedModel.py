import os
from typing import (
    Any,
    cast,
    ClassVar,
    Dict,
    Generic,
    List,
    Optional,
    Tuple,
    Type,
    TYPE_CHECKING,
    TypeVar,
    Union,
)

from wandb import util

from . import _dtypes
from ._private import MEDIA_TMP
from .base_types.Media import Media

if TYPE_CHECKING:  # pragma: no cover
    from wandb.apis.public import Artifact as PublicArtifact

    from ..wandb_artifacts import Artifact as LocalArtifact
    from ..wandb_run import Run as LocalRun

    import torch
    import sklearn
    import cloudpickle

    # TODO: make these richer
    ModelObjType = Any
    ModelFilePathType = str
    ModelDirPathType = str
    ModelPathType = Union[ModelFilePathType, ModelDirPathType]
    ModelType = Union[ModelPathType, ModelObjType]

    RegisteredAdaptersMapType = Dict[str, Type["_IModelAdapter"]]

    VectorElementType = Union[Type[int], Type[float]]
    VectorShapeType = Union[Tuple[int, ...], Tuple[int]]
    VariableType = Tuple[VectorShapeType, VectorElementType]
    SingularIOType = VariableType
    ListIOType = List[VariableType]
    NamedIOType = Dict[str, VariableType]
    ModelIOType = Union[SingularIOType, ListIOType, NamedIOType]


class _ModelAdapterRegistry(object):
    _registered_adapters: ClassVar[Optional[RegisteredAdaptersMapType]] = None

    @staticmethod
    def register_adapter(adapter: Type["_IModelAdapter"]) -> None:
        adapters = _ModelAdapterRegistry.registered_adapters()
        adapter_id = adapter.adapter_id()
        if adapter_id in adapters:
            raise ValueError(
                "Cannot add adapter with id {}, already exists".format(adapter_id)
            )
        adapters[adapter_id] = adapter

    @staticmethod
    def registered_adapters() -> RegisteredAdaptersMapType:
        if _ModelAdapterRegistry._registered_adapters is None:
            _ModelAdapterRegistry._registered_adapters = {}
        return _ModelAdapterRegistry._registered_adapters

    @staticmethod
    def load_adapter(adapter_id: str) -> Type["_IModelAdapter"]:
        selected_adapter = _ModelAdapterRegistry.registered_adapters()[adapter_id]
        if selected_adapter is None:
            raise ValueError(f"adapter {adapter_id} not registered")
        return selected_adapter

    @staticmethod
    def handles_model_or_path(
        adapter: Type["_IModelAdapter"], model_or_path: ModelType,
    ) -> bool:
        possible = False
        if _is_path(model_or_path):
            possible_single_file = _single_path_of_maybe_dir(model_or_path)
            if possible_single_file is not None:
                possible = adapter.can_load_path(possible_single_file)
            else:
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
        self, model_or_path: ModelType, adapter_id: Optional[str] = None,
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
            if self._path is None:
                raise ValueError("Error: SavedModel path not set")
            self._adapter = self._adapter_cls.init_from_path(self._path)
        return self._adapter

    @property
    def raw(self) -> ModelObjType:
        return self.adapter.raw()

    def to_json(self, run_or_artifact: Union["LocalRun", "LocalArtifact"]) -> dict:
        json_obj = super(SavedModel, self).to_json(run_or_artifact)
        json_obj["adapter_id"] = self.adapter.adapter_id
        json_obj["model_spec"] = self.adapter.model_spec().to_json()
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


def _single_path_of_maybe_dir(maybe_dir: str) -> Optional[str]:
    if os.path.isdir(maybe_dir):
        paths = os.listdir(maybe_dir)
        if len(paths) == 1:
            return os.path.join(maybe_dir, paths[0])
    return None


# TODO: Convert this to Weave
class _ModelSpec(object):
    _inputs: Optional[ModelIOType]
    _outputs: Optional[ModelIOType]

    def __init__(
        self, inputs: Optional[ModelIOType], outputs: Optional[ModelIOType]
    ) -> None:
        self._inputs = inputs
        self._outputs = outputs

    def to_json(self) -> Dict[str, Any]:
        return {
            "input_shape": self._inputs,
            "output_shape": self._outputs,
        }


ModelObjectType = TypeVar("ModelObjectType")


class _IModelAdapter(Generic[ModelObjectType]):
    _adapter_id: ClassVar[str]
    _internal_model: ModelObjectType

    def __init__(self, model: ModelObjectType) -> None:
        self._internal_model = model

    @classmethod
    def init_from_path(
        cls: Type["_IModelAdapter"], dir_or_file_path: ModelPathType
    ) -> "_IModelAdapter":
        raise NotImplementedError()

    @staticmethod
    def can_load_path(dir_or_file_path: ModelPathType) -> bool:
        """ Will only be a dir in the case that the dir contains more than 1 file.
        """
        raise NotImplementedError()

    @staticmethod
    def can_adapt_model(obj: Any) -> bool:
        raise NotImplementedError()

    def save_model(self, dir_path: ModelDirPathType) -> None:
        raise NotImplementedError()

    def model_spec(self) -> _ModelSpec:
        raise NotImplementedError()

    @classmethod
    def adapter_id(cls: Type["_IModelAdapter"]) -> str:
        return cls._adapter_id

    def raw(self) -> ModelObjectType:
        return self._internal_model


def _get_torch(hard: bool = False) -> "torch":
    return cast(
        "torch",
        util.get_module("torch", "ModelAdapter requires `torch`" if hard else None),
    )


class _PytorchModelAdapter(_IModelAdapter[torch.nn.Module]):
    _adapter_id = "pytorch"

    @classmethod
    def init_from_path(
        cls: Type["_IModelAdapter"], dir_or_file_path: ModelPathType
    ) -> "_IModelAdapter":
        return cls(_get_torch(True).load(dir_or_file_path))

    @staticmethod
    def can_load_path(dir_or_file_path: ModelPathType) -> bool:
        dynamic_torch = _get_torch()
        if (
            dynamic_torch is not None
            and not os.path.isdir(dir_or_file_path)
            and os.path.basename(dir_or_file_path).endswith(".pt")
        ):
            try:
                dynamic_torch.load(dir_or_file_path)
                return True
            except Exception:
                pass
        return False

    @staticmethod
    def can_adapt_model(obj: Any) -> bool:
        dynamic_torch = _get_torch()
        return dynamic_torch is not None and isinstance(obj, dynamic_torch.nn.Module)

    def save_model(self, dir_path: ModelDirPathType) -> None:
        target_path = os.path.join(dir_path, "model.pt")
        dynamic_torch = _get_torch(True)
        dynamic_torch.save(self._internal_model, target_path)

    def model_spec(self) -> _ModelSpec:
        # TODO
        return _ModelSpec(None, None)


def _get_sklearn(hard: bool = False) -> "sklearn":
    return cast(
        "sklearn",
        util.get_module("sklearn", "ModelAdapter requires `sklearn`" if hard else None),
    )


def _get_cloudpickle(hard: bool = False) -> "cloudpickle":
    return cast(
        "cloudpickle",
        util.get_module(
            "cloudpickle", "ModelAdapter requires `cloudpickle`" if hard else None
        ),
    )


class _SklearnModelAdapter(_IModelAdapter[torch.nn.Module]):
    _adapter_id = "sklearn"

    @classmethod
    def init_from_path(
        cls: Type["_IModelAdapter"], dir_or_file_path: ModelPathType
    ) -> "_IModelAdapter":
        with open(dir_or_file_path, "rb") as file:
            model = _get_cloudpickle(True).load(file)
        return cls(model)

    @staticmethod
    def can_load_path(dir_or_file_path: ModelPathType) -> bool:
        dynamic_sklearn = _get_sklearn()
        dynamic_cloudpickle = _get_cloudpickle()
        if (
            dynamic_sklearn is not None
            and dynamic_cloudpickle is not None
            and not os.path.isdir(dir_or_file_path)
            and os.path.basename(dir_or_file_path).endswith(".pkl")
        ):
            try:
                valid = False
                with open(dir_or_file_path, "rb") as file:
                    model = dynamic_cloudpickle.load(file)
                    valid = (
                        dynamic_sklearn.base.is_classifier(model)
                        or dynamic_sklearn.base.is_outlier_detector(model)
                        or dynamic_sklearn.base.is_regressor(model)
                    )
                return valid
            except Exception:
                pass
        return False

    @staticmethod
    def can_adapt_model(obj: Any) -> bool:
        dynamic_sklearn = _get_sklearn()
        return (
            dynamic_sklearn is not None
            and dynamic_sklearn.base.is_classifier(obj)
            or dynamic_sklearn.base.is_outlier_detector(obj)
            or dynamic_sklearn.base.is_regressor(obj)
        )

    def save_model(self, dir_path: ModelDirPathType) -> None:
        dynamic_cloudpickle = _get_cloudpickle(True)
        target_path = os.path.join(dir_path, "model.pkl")
        with open(target_path, "wb") as file:
            dynamic_cloudpickle.dump(self._internal_model, file)

    def model_spec(self) -> _ModelSpec:
        # TODO
        return _ModelSpec(None, None)


# Leaving this here for when we want to release this
# class _PytorchTorchScriptModelAdapter(_IModelAdapter[torch.nn.Module]):
#     _adapter_id = "pytorch-torchscript"

#     @classmethod
#     def init_from_path(
#         cls: Type["_IModelAdapter"], dir_or_file_path: ModelPathType
#     ) -> "_IModelAdapter":
#         return util.get_module('torch', "_PytorchTorchScriptModelAdapter requires `torch`").jit.load(dir_or_file_path)

#     @staticmethod
#     def can_load_path(dir_or_file_path: ModelPathType) -> bool:
#         dynamic_torch = util.get_module('torch')
#         if dynamic_torch is not None and not os.path.isdir(dir_or_file_path) and os.path.basename(dir_or_file_path).endswith('.pt'):
#             try:
#                 dynamic_torch.jit.load(dir_or_file_path)
#                 return True
#             except Exception:
#                 pass
#         return False

#     @staticmethod
#     def can_adapt_model(obj: Any) -> bool:
#         dynamic_torch = util.get_module('torch')
#         if dynamic_torch is not None:
#             if isinstance(obj, dynamic_torch.jit.ScriptModule):
#                 return True
#             elif isinstance(obj, dynamic_torch.nn.Module):
#                 try:
#                     dynamic_torch.jit.script(obj)
#                     return False
#                 except Exception:
#                     pass
#         return False

#     def save_model(self, dir_path: ModelDirPathType) -> None:
#         target_path = os.path.join(dir_path, 'model_scripted.pt')
#         dynamic_torch = util.get_module('torch', "_PytorchTorchScriptModelAdapter requires `torch`")
#         if isinstance(self._internal_model, dynamic_torch.jit.ScriptModule):
#             self._internal_model.save(target_path)
#         else:
#             model_scripted = dynamic_torch.jit.script(self._internal_model)
#             model_scripted.save(target_path)

#     def model_spec(self) -> _ModelSpec:
#         # TODO
#         return _ModelSpec(None, None)


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
            return cls(
                py_obj.adapter.adapter_id(), py_obj.adapter.model_spec().to_json()
            )


_dtypes.TypeRegistry.add(_SavedModelType)
