import os
from typing import (
    Any,
    cast,
    ClassVar,
    Dict,
    Generic,
    Optional,
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
    import tensorflow

    # TODO: make these richer
    ModelObjType = Any
    ModelFilePathType = str
    ModelDirPathType = str
    ModelPathType = Union[ModelFilePathType, ModelDirPathType]
    ModelType = Union[ModelPathType, ModelObjType]

    RegisteredAdaptersMapType = Dict[str, Type["_IModelAdapter"]]


class _ModelAdapterRegistry(object):
    _registered_adapters: ClassVar[Optional["RegisteredAdaptersMapType"]] = None

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
    def registered_adapters() -> "RegisteredAdaptersMapType":
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
    def maybe_init_adapter_from_model_or_path(
        adapter_cls: Type["_IModelAdapter"], model_or_path: "ModelType",
    ) -> Optional["_IModelAdapter"]:
        possible_adapter: Optional["_IModelAdapter"] = None
        if _is_path(model_or_path):
            possible_adapter = adapter_cls.maybe_init_from_path(model_or_path)
        elif adapter_cls.can_adapt_model(model_or_path):
            possible_adapter = adapter_cls(model_or_path)
        return possible_adapter

    @staticmethod
    def find_suitable_adapter(
        model_or_path: "ModelType", adapter_id: Optional[str] = None
    ) -> Optional["_IModelAdapter"]:
        adapter_classes = _ModelAdapterRegistry.registered_adapters()
        adapter: Optional["_IModelAdapter"] = None
        if adapter_id is None:
            for key in adapter_classes:
                adapter = _ModelAdapterRegistry.maybe_init_adapter_from_model_or_path(
                    adapter_classes[key], model_or_path
                )
                if adapter is not None:
                    break
        elif adapter_id in adapter_classes:
            adapter = _ModelAdapterRegistry.maybe_init_adapter_from_model_or_path(
                adapter_classes[adapter_id], model_or_path
            )
        return adapter


class SavedModel(Media):
    _log_type: ClassVar[str] = "saved-model"
    _adapter: "_IModelAdapter"

    def __init__(
        self, model_or_path: "ModelType", adapter_id: Optional[str] = None,
    ) -> None:
        super(SavedModel, self).__init__()
        _adapter = _ModelAdapterRegistry.find_suitable_adapter(
            model_or_path, adapter_id
        )
        assert (
            _adapter is not None
        ), f"No suitable adapter found for model {model_or_path}"
        self._adapter = _adapter
        if _is_path(model_or_path):
            # TODO: make media support a directory path
            self._set_file(model_or_path)
        else:
            # We immediately write the file(s) in case the user modifies the model
            # after creating the SavedModel (ie. continues training)
            tmp_path = os.path.join(MEDIA_TMP.name, str(util.generate_id()))
            self._adapter.save_model(tmp_path)
            # TODO: make media support a directory path (this is going to be non-trivial)
            self._set_file(tmp_path, is_tmp=True)

    def model_obj(self) -> "ModelObjType":
        return self._adapter.model_obj()

    def to_json(self, run_or_artifact: Union["LocalRun", "LocalArtifact"]) -> dict:
        json_obj = super(SavedModel, self).to_json(run_or_artifact)
        json_obj["adapter_id"] = self._adapter.adapter_id()
        return json_obj

    @classmethod
    def from_json(
        cls: Type["SavedModel"], json_obj: dict, source_artifact: "PublicArtifact"
    ) -> "SavedModel":
        # TODO: make download support directories
        return cls(
            source_artifact.get_path(json_obj["path"]).download(),
            json_obj["adapter_id"],
        )


def _is_path(model_or_path: "ModelType") -> bool:
    return isinstance(model_or_path, str) and os.path.exists(model_or_path)


def _single_path_of_maybe_dir(maybe_dir: str) -> Optional[str]:
    if os.path.isdir(maybe_dir):
        paths = os.listdir(maybe_dir)
        if len(paths) == 1:
            return os.path.join(maybe_dir, paths[0])
    return None


ModelObjectType = TypeVar("ModelObjectType")


class _IModelAdapter(Generic[ModelObjectType]):
    """_IModelAdapter is an interface for adapting a model in the form of a runtime python object
    to work with the SavedModel media type. The adapter is responsible for converting the model
    to one or more files that can be saved to disk as well as providing a method for loading the
    model from disk.

    At a minimum, implementers of _IModelAdapter must implement the following:
        - `_adapter_id` should be set to a globally unique identifier for the adapter (and never changed)
        - (optional) `_can_init_from_directory` should return True if the adapter can be initialized from a directory
        - `_unsafe_maybe_init_from_path` should return a new instance of the implementing class if possible
        - `_unsafe_can_adapt_model` should return True if the adapter can adapt the given model
        - `save_model` should save the model to the given directory
    """

    # Class Vars
    _adapter_id: ClassVar[str]
    _can_init_from_directory: ClassVar[bool] = False

    # Instance Vars
    _model_obj: ModelObjectType

    def __init__(self, model: ModelObjectType) -> None:
        """Contruction of the adapter will take an object of type `ModelObjectType`.
        """
        super(_IModelAdapter, self).__init__()
        assert self.can_adapt_model(
            model
        ), f"{self.__class__} is unable to adapt model {model}"
        self._model_obj = model

    @classmethod
    def maybe_init_from_path(
        cls: Type["_IModelAdapter"], dir_or_file_path: "ModelPathType"
    ) -> Optional["_IModelAdapter"]:
        """Accepts a path (of a directory or single file) and possibly
        returns a new instance of the class.
        """
        try:
            possible_single_file = _single_path_of_maybe_dir(dir_or_file_path)
            if possible_single_file is not None:
                return cls._unsafe_maybe_init_from_path(possible_single_file)
            elif cls._can_init_from_directory:
                return cls._unsafe_maybe_init_from_path(dir_or_file_path)
        except Exception:
            pass
        return None

    @classmethod
    def can_adapt_model(cls: Type["_IModelAdapter"], obj: Any) -> bool:
        """Determines if the class is capable of adapting the provided python object.
        """
        try:
            return cls._unsafe_can_adapt_model(obj)
        except Exception:
            return False

    @classmethod
    def adapter_id(cls: Type["_IModelAdapter"]) -> str:
        assert isinstance(cls._adapter_id, str), "adapter_id must be a string"
        return cls._adapter_id

    def model_obj(self) -> ModelObjectType:
        return self._model_obj

    @classmethod
    def _unsafe_maybe_init_from_path(
        cls: Type["_IModelAdapter"], dir_or_file_path: "ModelPathType"
    ) -> Optional["_IModelAdapter"]:
        """Accepts a path (pointing to a directory or single file) and possibly
        returns a new instance of the class. A directory will only be passed if
        `_can_init_from_directory` is True. For convenience, if the caller passes a
        directory to `maybe_init_from_path` and that directory contains a single file,
        then the single file path will be passed to this method.

        Subclass developers are expected to override this method instead of `maybe_init_from_path`.
        It is OK to throw errors in this method - which should be interpretted by the
        caller as an invalid path for this class.
        """
        raise NotImplementedError()

    @staticmethod
    def _unsafe_can_adapt_model(obj: Any) -> bool:
        """Determines if the class is capable of adapting the provided python object.
        """
        raise NotImplementedError()

    def save_model(self, dir_path: "ModelDirPathType") -> None:
        """Save the model to disk. The method will receive a directory path which all
        files needed for deserialization should be saved. A directory will always be passed,
        even if `_can_init_from_directory` is False. If this method saves a single file to such
        directory, that single file will be used when calling `_unsafe_maybe_init_from_path`.
        """
        raise NotImplementedError()


def _get_torch() -> "torch":
    return cast("torch", util.get_module("torch", "ModelAdapter requires `torch`"),)


class _PytorchModelAdapter(_IModelAdapter["torch.nn.Module"]):
    _adapter_id = "pytorch"

    @classmethod
    def _unsafe_maybe_init_from_path(
        cls: Type["_IModelAdapter"], dir_or_file_path: "ModelPathType"
    ) -> Optional["_IModelAdapter"]:
        return cls(_get_torch().load(dir_or_file_path))

    @staticmethod
    def _unsafe_can_adapt_model(obj: Any) -> bool:
        return isinstance(obj, _get_torch().nn.Module)

    def save_model(self, dir_path: "ModelDirPathType") -> None:
        _get_torch().save(self.model_obj(), os.path.join(dir_path, "model.pt"))


def _get_sklearn() -> "sklearn":
    return cast(
        "sklearn", util.get_module("sklearn", "ModelAdapter requires `sklearn`"),
    )


def _get_cloudpickle() -> "cloudpickle":
    return cast(
        "cloudpickle",
        util.get_module("cloudpickle", "ModelAdapter requires `cloudpickle`"),
    )


class _SklearnModelAdapter(_IModelAdapter["sklearn.base.BaseEstimator"]):
    _adapter_id = "sklearn"

    @classmethod
    def _unsafe_maybe_init_from_path(
        cls: Type["_IModelAdapter"], dir_or_file_path: "ModelPathType"
    ) -> Optional["_IModelAdapter"]:
        with open(dir_or_file_path, "rb") as file:
            model = _get_cloudpickle().load(file)
        return cls(model)

    @staticmethod
    def _unsafe_can_adapt_model(obj: Any) -> bool:
        dynamic_sklearn = _get_sklearn()
        return cast(
            bool,
            (
                dynamic_sklearn.base.is_classifier(obj)
                or dynamic_sklearn.base.is_outlier_detector(obj)
                or dynamic_sklearn.base.is_regressor(obj)
            ),
        )

    def save_model(self, dir_path: "ModelDirPathType") -> None:
        dynamic_cloudpickle = _get_cloudpickle()
        target_path = os.path.join(dir_path, "model.pkl")
        with open(target_path, "wb") as file:
            dynamic_cloudpickle.dump(self.model_obj(), file)


def _get_tf_keras() -> "tensorflow.keras":
    return cast(
        "tensorflow",
        util.get_module("tensorflow", "ModelAdapter requires `tensorflow`"),
    ).keras


class _TensorflowKerasSavedModelAdapter(_IModelAdapter["tensorflow.keras.Model"]):
    _adapter_id = "tf-keras-savedmodel"
    _can_init_from_directory = True

    @classmethod
    def _unsafe_maybe_init_from_path(
        cls: Type["_IModelAdapter"], dir_or_file_path: "ModelPathType"
    ) -> Optional["_IModelAdapter"]:
        return cls(_get_tf_keras().models.load_model(dir_or_file_path))

    @staticmethod
    def _unsafe_can_adapt_model(obj: Any) -> bool:
        return isinstance(obj, _get_tf_keras().models.Model)

    def save_model(self, dir_path: "ModelDirPathType") -> None:
        _get_tf_keras().models.save_model(
            self.model_obj(), dir_path, include_optimizer=True
        )


# Note: Thinking about how the type system works now, I think
# we will be able to write a cleaner interface that allows the
# media type to encode the type of the data. However, it might be
# worth waiting for Shawn to finish his Python Weave implementation.
class _SavedModelType(_dtypes.Type):
    name = "saved-model"
    types = [SavedModel]

    def __init__(self, adapter_id: str) -> None:
        self.params.update({"adapter_id": adapter_id})

    @classmethod
    def from_obj(cls, py_obj: Optional[Any] = None) -> "_SavedModelType":
        if not isinstance(py_obj, SavedModel):
            raise TypeError("py_obj must be a SavedModel")
        else:
            return cls(py_obj._adapter.adapter_id())


_dtypes.TypeRegistry.add(_SavedModelType)
_ModelAdapterRegistry.register_adapter(_PytorchModelAdapter)
_ModelAdapterRegistry.register_adapter(_SklearnModelAdapter)
_ModelAdapterRegistry.register_adapter(_TensorflowKerasSavedModelAdapter)
