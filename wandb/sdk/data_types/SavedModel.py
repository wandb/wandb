import os
import shutil
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
from .base_types.WBValue import WBValue

if TYPE_CHECKING:  # pragma: no cover
    from wandb.apis.public import Artifact as PublicArtifact

    from ..wandb_artifacts import Artifact as LocalArtifact
    from ..wandb_run import Run as LocalRun

    import cloudpickle
    import torch
    import sklearn
    import tensorflow

    # TODO: make these richer - for now this is fine.
    GlobalModelObjType = Any
    ModelFilePathType = str
    ModelDirPathType = str
    PathType = Union[ModelFilePathType, ModelDirPathType]
    ManyPathType = Union[PathType, List[PathType], Dict[str, PathType]]
    ModelType = Union[PathType, GlobalModelObjType]

    RegisteredAdaptersMapType = Dict[str, Type["_IModelAdapter"]]
    SuitableAdapterTuple = Tuple[GlobalModelObjType, Type["_IModelAdapter"]]

    DataTypeContainerInterfaceType = LocalArtifact


class SavedModel(WBValue):
    _log_type: ClassVar[str] = "saved-model"
    _adapter: Type["_IModelAdapter"]
    _model_obj: Optional["GlobalModelObjType"]
    _path: str

    def __init__(
        self, model_or_path: "ModelType", adapter_id: Optional[str] = None,
    ) -> None:
        super(SavedModel, self).__init__()
        model_adapter_tuple = _ModelAdapterRegistry.find_suitable_adapter(
            model_or_path, adapter_id
        )
        assert (
            model_adapter_tuple is not None
        ), f"No suitable adapter ({adapter_id}) found for model {model_or_path}"

        self._adapter = model_adapter_tuple[1]
        self._path = self._make_target_path()

        if _is_path(model_or_path):

            if os.path.isfile(model_or_path):
                assert os.path.splitext(self._path)[1] is not None
                shutil.copyfile(model_or_path, self._path)
            elif os.path.isdir(model_or_path):
                assert os.path.splitext(self._path)[1] == ""
                shutil.copytree(model_or_path, self._path)
            else:
                raise ValueError(
                    f"Expected a path to a file or directory, got {model_or_path}"
                )

            # This will be a fresh copy from disk, so it is OK to set now
            self._model_obj = model_adapter_tuple[0]
        else:
            # We immediately write the file(s) in case the user modifies the model
            # after creating the SavedModel (ie. continues training)
            self._adapter.save_model(model_adapter_tuple[0], self._path)
            # Important: set this to None, so any model_obj() read will lazy load from disk (cached)
            self._model_obj = None

    def _make_target_path(self) -> str:
        tmp_path = os.path.abspath(
            os.path.join(MEDIA_TMP.name, str(util.generate_id()))
        )
        if self._adapter.path_extension() != "":
            tmp_path += "." + self._adapter.path_extension()
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        return tmp_path

    def model_obj(self) -> "GlobalModelObjType":
        if self._model_obj is None:
            model_obj = self._adapter.model_obj_from_path(self._path)
            assert model_obj is not None, f"Could not load model from path {self._path}"
            self._model_obj = model_obj
            return model_obj
        return self._model_obj

    def to_json(self, run_or_artifact: Union["LocalRun", "LocalArtifact"]) -> dict:
        import wandb

        if isinstance(run_or_artifact, wandb.wandb_sdk.wandb_run.Run):
            raise ValueError("SavedModel cannot be added to run - must use artifact")
        artifact = run_or_artifact
        json_obj = {
            "type": self._log_type,
            "adapter_id": self._adapter.adapter_id(),
        }
        if os.path.isfile(self._path):
            # If the path is a file, then we can just add it to the artifact,
            # First checking to see if the artifact already has the file (use the cache)
            # Else, add it directly, allowing the artifact adder to rename the file deterministically.
            already_added_path = artifact.get_added_local_path_name(self._path)
            if already_added_path is not None:
                json_obj["path"] = already_added_path
            else:
                target_path = os.path.join(
                    ".wb_data", "saved_models", os.path.basename(self._path)
                )
                json_obj["path"] = artifact.add_file(self._path, target_path, True).path
        elif os.path.isdir(self._path):
            from wandb.sdk.interface.artifacts import md5_files_b64, b64_string_to_hex

            # Here, we need to add a directory of files to the artifact. The directory must be named deterministically based on the contents of the directory.
            # but the files themselves need to have their name preserved. This functionality really should be added to the artifact, but doing it here
            # for now until we get the patterns down.
            file_paths = []
            for dirpath, _, filenames in os.walk(self._path, topdown=True):
                for fn in filenames:
                    file_paths.append(os.path.join(dirpath, fn))
            dirname = b64_string_to_hex(md5_files_b64(file_paths))[:20]
            target_path = os.path.join(".wb_data", "saved_models", dirname)
            artifact.add_dir(self._path, target_path)
            json_obj["path"] = target_path
        else:
            raise ValueError(
                f"Expected a path to a file or directory, got {self._path}"
            )

        return json_obj

    @classmethod
    def from_json(
        cls: Type["SavedModel"], json_obj: dict, source_artifact: "PublicArtifact"
    ) -> "SavedModel":
        path = json_obj["path"]
        entry = source_artifact.manifest.entries.get(path)
        if entry is not None:
            dl_path = entry.download()
        else:
            # assume it is directory: (would be nice to parallelize)
            dl_path = None
            for p, e in source_artifact.manifest.entries.items():
                if p.startswith(path):
                    example_path = e.download()
                    if dl_path is None:
                        root = example_path[: -len(p)]
                        dl_path = os.path.join(root, path)
        return cls(dl_path, json_obj["adapter_id"])


def _is_path(model_or_path: "ModelType") -> bool:
    return isinstance(model_or_path, str) and os.path.exists(model_or_path)


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
    def maybe_adapter_from_model_or_path(
        adapter_cls: Type["_IModelAdapter"], model_or_path: "ModelType",
    ) -> Optional["SuitableAdapterTuple"]:
        model_adapter_tuple: Optional["SuitableAdapterTuple"] = None
        if _is_path(model_or_path):
            possible_model = adapter_cls.model_obj_from_path(model_or_path)
            if possible_model is not None:
                model_adapter_tuple = (possible_model, adapter_cls)
        elif adapter_cls.can_adapt_model_obj(model_or_path):
            model_adapter_tuple = (model_or_path, adapter_cls)
        return model_adapter_tuple

    @staticmethod
    def find_suitable_adapter(
        model_or_path: "ModelType", adapter_id: Optional[str] = None
    ) -> Optional["SuitableAdapterTuple"]:
        adapter_classes = _ModelAdapterRegistry.registered_adapters()
        model_adapter_tuple: Optional["SuitableAdapterTuple"] = None
        if adapter_id is None:
            for key in adapter_classes:
                model_adapter_tuple = _ModelAdapterRegistry.maybe_adapter_from_model_or_path(
                    adapter_classes[key], model_or_path
                )
                if model_adapter_tuple is not None:
                    break
        elif adapter_id in adapter_classes:
            model_adapter_tuple = _ModelAdapterRegistry.maybe_adapter_from_model_or_path(
                adapter_classes[adapter_id], model_or_path
            )
        return model_adapter_tuple


AdapterModelObjType = TypeVar("AdapterModelObjType")


class _IModelAdapter(Generic[AdapterModelObjType]):
    """_IModelAdapter is an interface for adapting a model in the form of a runtime python object
    to work with the SavedModel media type. The adapter is responsible for converting the model
    to one or more files that can be saved to disk as well as providing a method for loading the
    model from disk.

    At a minimum, implementers of _IModelAdapter must implement the following:
        - `_adapter_id` should be set to a globally unique identifier for the adapter (and never changed)
        - `_path_extension` should be set to the file extension of the model file - empty string means directory
        - `_unsafe_model_obj_from_path` should return a new instance of the implementing class if possible
        - `_unsafe_can_adapt_model_obj` should return True if the adapter can adapt the given model
        - `save_model` should save the model to the given directory.
    """

    # Class Vars
    _adapter_id: ClassVar[str]
    _path_extension: ClassVar[str]

    @classmethod
    def model_obj_from_path(
        cls: Type["_IModelAdapter"], dir_or_file_path: "PathType"
    ) -> Optional[AdapterModelObjType]:
        """Accepts a path (of a directory or single file) and possibly
        returns a new instance of the class.
        """
        try:
            if os.path.isdir(dir_or_file_path) and cls.path_extension() == "":
                maybe_model = cls._unsafe_model_obj_from_path(dir_or_file_path)
            elif (
                os.path.isfile(dir_or_file_path)
                and os.path.splitext(dir_or_file_path)[1] == f".{cls.path_extension()}"
            ):
                maybe_model = cls._unsafe_model_obj_from_path(dir_or_file_path)

            if cls.can_adapt_model_obj(maybe_model):
                return maybe_model
        except Exception:
            pass
        return None

    @classmethod
    def can_adapt_model_obj(
        cls: Type["_IModelAdapter"], obj: "GlobalModelObjType"
    ) -> bool:
        """Determines if the class is capable of adapting the provided python object.
        """
        try:
            return cls._unsafe_can_adapt_model_obj(obj)
        except Exception:
            return False

    @classmethod
    def adapter_id(cls: Type["_IModelAdapter"]) -> str:
        assert isinstance(cls._adapter_id, str), "_adapter_id must be a string"
        return cls._adapter_id

    @classmethod
    def path_extension(cls: Type["_IModelAdapter"]) -> str:
        assert isinstance(cls._path_extension, str), "_path_extension must be a string"
        return cls._path_extension

    @staticmethod
    def _unsafe_model_obj_from_path(
        dir_or_file_path: "PathType",
    ) -> AdapterModelObjType:
        """Accepts a path (pointing to a directory or single file) and possibly
        returns a new instance of the class. A directory will only be passed if
        `_can_init_from_directory` is True. For convenience, if the caller passes a
        directory to `model_obj_from_path` and that directory contains a single file,
        then the single file path will be passed to this method.

        Subclass developers are expected to override this method instead of `model_obj_from_path`.
        It is OK to throw errors in this method - which should be interpretted by the
        caller as an invalid path for this class.
        """
        raise NotImplementedError()

    @staticmethod
    def _unsafe_can_adapt_model_obj(obj: "GlobalModelObjType") -> bool:
        """Determines if the class is capable of adapting the provided python object.
        """
        raise NotImplementedError()

    @staticmethod
    def save_model(
        model_obj: AdapterModelObjType, dir_or_file_path: "PathType"
    ) -> None:
        """Save the model to disk. The method will receive a directory path which all
        files needed for deserialization should be saved. A directory will always be passed if
        _path_extension is an empty string, else a single file will be passed.
        """
        raise NotImplementedError()


def _get_cloudpickle() -> "cloudpickle":
    return cast(
        "cloudpickle",
        util.get_module("cloudpickle", "ModelAdapter requires `cloudpickle`"),
    )


def _get_torch() -> "torch":
    return cast("torch", util.get_module("torch", "ModelAdapter requires `torch`"),)


class _PytorchModelAdapter(_IModelAdapter["torch.nn.Module"]):
    _adapter_id = "pytorch"
    _path_extension = "pt"

    @staticmethod
    def _unsafe_model_obj_from_path(dir_or_file_path: "PathType") -> "torch.nn.Module":
        return _get_torch().load(dir_or_file_path)

    @staticmethod
    def _unsafe_can_adapt_model_obj(obj: "GlobalModelObjType") -> bool:
        return isinstance(obj, _get_torch().nn.Module)

    @staticmethod
    def save_model(
        model_obj: AdapterModelObjType, dir_or_file_path: "PathType"
    ) -> None:
        _get_torch().save(
            model_obj, dir_or_file_path, pickle_module=_get_cloudpickle(),
        )


def _get_sklearn() -> "sklearn":
    return cast(
        "sklearn", util.get_module("sklearn", "ModelAdapter requires `sklearn`"),
    )


class _SklearnModelAdapter(_IModelAdapter["sklearn.base.BaseEstimator"]):
    _adapter_id = "sklearn"
    _path_extension = "pkl"

    @staticmethod
    def _unsafe_model_obj_from_path(
        dir_or_file_path: "PathType",
    ) -> "sklearn.base.BaseEstimator":
        with open(dir_or_file_path, "rb") as file:
            model = _get_cloudpickle().load(file)
        return model

    @staticmethod
    def _unsafe_can_adapt_model_obj(obj: "GlobalModelObjType") -> bool:
        dynamic_sklearn = _get_sklearn()
        return cast(
            bool,
            (
                dynamic_sklearn.base.is_classifier(obj)
                or dynamic_sklearn.base.is_outlier_detector(obj)
                or dynamic_sklearn.base.is_regressor(obj)
            ),
        )

    @staticmethod
    def save_model(
        model_obj: "sklearn.base.BaseEstimator", dir_or_file_path: "PathType"
    ) -> None:
        dynamic_cloudpickle = _get_cloudpickle()
        with open(dir_or_file_path, "wb") as file:
            dynamic_cloudpickle.dump(model_obj, file)


def _get_tf_keras() -> "tensorflow.keras":
    return cast(
        "tensorflow",
        util.get_module("tensorflow", "ModelAdapter requires `tensorflow`"),
    ).keras


class _TensorflowKerasSavedModelAdapter(_IModelAdapter["tensorflow.keras.Model"]):
    _adapter_id = "tf-keras-savedmodel"
    _path_extension = ""

    @staticmethod
    def _unsafe_model_obj_from_path(
        dir_or_file_path: "PathType",
    ) -> "tensorflow.keras.Model":
        return _get_tf_keras().models.load_model(dir_or_file_path)

    @staticmethod
    def _unsafe_can_adapt_model_obj(obj: "GlobalModelObjType") -> bool:
        return isinstance(obj, _get_tf_keras().models.Model)

    @staticmethod
    def save_model(
        model_obj: "tensorflow.keras.Model", dir_or_file_path: "PathType"
    ) -> None:
        _get_tf_keras().models.save_model(
            model_obj, dir_or_file_path, include_optimizer=True
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
