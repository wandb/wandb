import codecs
import hashlib
import json
import logging
import numbers
import os
import re
import shutil
import sys

import six
from six.moves.collections_abc import Sequence as SixSequence
import wandb
from wandb import util
from wandb._globals import _datatypes_callback
from wandb.compat import tempfile
from wandb.util import has_num

from .interface import _dtypes

if wandb.TYPE_CHECKING:
    from typing import (
        TYPE_CHECKING,
        ClassVar,
        Dict,
        Optional,
        Type,
        Union,
        Sequence,
        Tuple,
        Set,
        Any,
        List,
        cast,
    )

    if TYPE_CHECKING:  # pragma: no cover
        from .interface.artifacts import ArtifactEntry
        from .wandb_artifacts import Artifact as LocalArtifact
        from .wandb_run import Run as LocalRun
        from wandb.apis.public import Artifact as PublicArtifact
        import numpy as np  # type: ignore
        import pandas as pd  # type: ignore
        import matplotlib  # type: ignore
        import plotly  # type: ignore
        import PIL  # type: ignore
        import torch  # type: ignore
        from typing import TextIO

        TypeMappingType = Dict[str, Type["WBValue"]]
        NumpyHistogram = Tuple[np.ndarray, np.ndarray]
        ValToJsonType = Union[
            dict,
            "WBValue",
            Sequence["WBValue"],
            "plotly.Figure",
            "matplotlib.artist.Artist",
            "pd.DataFrame",
            object,
        ]
        ImageDataType = Union[
            "matplotlib.artist.Artist", "PIL.Image", "TorchTensorType", "np.ndarray"
        ]
        ImageDataOrPathType = Union[str, "Image", ImageDataType]
        TorchTensorType = Union["torch.Tensor", "torch.Variable"]

_MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")
_DATA_FRAMES_SUBDIR = os.path.join("media", "data_frames")


class _WBValueArtifactSource(object):
    # artifact: "PublicArtifact"
    # name: Optional[str]

    def __init__(self, artifact, name = None):
        self.artifact = artifact
        self.name = name


class _WBValueArtifactTarget(object):
    # artifact: "LocalArtifact"
    # name: Optional[str]

    def __init__(self, artifact, name = None):
        self.artifact = artifact
        self.name = name


class WBValue(object):
    """
    Abstract parent class for things that can be logged by `wandb.log()` and
    visualized by wandb.

    The objects will be serialized as JSON and always have a _type attribute
    that indicates how to interpret the other fields.
    """

    # Class Attributes
    _type_mapping = None
    # override _log_type to indicate the type which the subclass deserializes
    _log_type = None

    # Instance Attributes
    # _artifact_source: Optional[_WBValueArtifactSource]
    # _artifact_target: Optional[_WBValueArtifactTarget]

    def __init__(self):
        self._artifact_source = None
        self._artifact_target = None

    def to_json(self, run_or_artifact):
        """Serializes the object into a JSON blob, using a run or artifact to store additional data.

        Args:
            run_or_artifact (wandb.Run | wandb.Artifact): the Run or Artifact for which this object should be generating
            JSON for - this is useful to to store additional data if needed.

        Returns:
            dict: JSON representation
        """
        raise NotImplementedError

    @classmethod
    def from_json(
        cls, json_obj, source_artifact
    ):
        """Deserialize a `json_obj` into it's class representation. If additional resources were stored in the
        `run_or_artifact` artifact during the `to_json` call, then those resources are expected to be in
        the `source_artifact`.

        Args:
            json_obj (dict): A JSON dictionary to deserialize
            source_artifact (wandb.Artifact): An artifact which will hold any additional resources which were stored
            during the `to_json` function.
        """
        raise NotImplementedError

    @classmethod
    def with_suffix(cls, name, filetype = "json"):
        """Helper function to return the name with suffix added if not already

        Args:
            name (str): the name of the file
            filetype (str, optional): the filetype to use. Defaults to "json".

        Returns:
            str: a filename which is suffixed with it's `_log_type` followed by the filetype
        """
        if cls._log_type is not None:
            suffix = cls._log_type + "." + filetype
        else:
            suffix = filetype
        if not name.endswith(suffix):
            return name + "." + suffix
        return name

    @staticmethod
    def init_from_json(
        json_obj, source_artifact
    ):
        """Looks through all subclasses and tries to match the json obj with the class which created it. It will then
        call that subclass' `from_json` method. Importantly, this function will set the return object's `source_artifact`
        attribute to the passed in source artifact. This is critical for artifact bookkeeping. If you choose to create
        a wandb.Value via it's `from_json` method, make sure to properly set this `artifact_source` to avoid data duplication.

        Args:
            json_obj (dict): A JSON dictionary to deserialize. It must contain a `_type` key. The value of
            this key is used to lookup the correct subclass to use.
            source_artifact (wandb.Artifact): An artifact which will hold any additional resources which were stored
            during the `to_json` function.

        Returns:
            wandb.Value: a newly created instance of a subclass of wandb.Value
        """
        class_option = WBValue.type_mapping().get(json_obj["_type"])
        if class_option is not None:
            obj = class_option.from_json(json_obj, source_artifact)
            obj._set_artifact_source(source_artifact)
            return obj

        return None

    @staticmethod
    def type_mapping():
        """Returns a map from `_log_type` to subclass. Used to lookup correct types for deserialization.

        Returns:
            dict: dictionary of str:class
        """
        if WBValue._type_mapping is None:
            WBValue._type_mapping = {}
            frontier = [WBValue]
            explored = set([])
            while len(frontier) > 0:
                class_option = frontier.pop()
                explored.add(class_option)
                if class_option._log_type is not None:
                    WBValue._type_mapping[class_option._log_type] = class_option
                for subclass in class_option.__subclasses__():
                    if subclass not in explored:
                        frontier.append(subclass)
        return WBValue._type_mapping

    def __eq__(self, other):
        return id(self) == id(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def to_data_array(self):
        """Converts the object to a list of primitives representing the underlying data"""
        raise NotImplementedError

    def _set_artifact_source(
        self, artifact, name = None
    ):
        assert (
            self._artifact_source is None
        ), "Cannot update artifact_source. Existing source: {}/{}".format(
            self._artifact_source.artifact, self._artifact_source.name
        )
        self._artifact_source = _WBValueArtifactSource(artifact, name)

    def _set_artifact_target(
        self, artifact, name = None
    ):
        assert (
            self._artifact_target is None
        ), "Cannot update artifact_target. Existing target: {}/{}".format(
            self._artifact_target.artifact, self._artifact_target.name
        )
        self._artifact_target = _WBValueArtifactTarget(artifact, name)

    def _get_artifact_reference_entry(self):
        ref_entry = None
        # If the object is coming from another artifact
        if self._artifact_source and self._artifact_source.name:
            ref_entry = self._artifact_source.artifact.get_path(
                type(self).with_suffix(self._artifact_source.name)
            )
        # Else, if the object is destined for another artifact
        elif (
            self._artifact_target
            and self._artifact_target.name
            and self._artifact_target.artifact._logged_artifact is not None
        ):
            # Currently, we do not have a way to obtain a reference URL without waiting for the
            # upstream artifact to be logged. This implies that this only works online as well.
            self._artifact_target.artifact.wait()
            ref_entry = self._artifact_target.artifact.get_path(
                type(self).with_suffix(self._artifact_target.name)
            )
        return ref_entry


class Histogram(WBValue):
    """wandb class for histograms.

    This object works just like numpy's histogram function
    https://docs.scipy.org/doc/numpy/reference/generated/numpy.histogram.html

    Examples:
        Generate histogram from a sequence
        ```python
        wandb.Histogram([1,2,3])
        ```

        Efficiently initialize from np.histogram.
        ```python
        hist = np.histogram(data)
        wandb.Histogram(np_histogram=hist)
        ```

    Arguments:
        sequence: (array_like) input data for histogram
        np_histogram: (numpy histogram) alternative input of a precoomputed histogram
        num_bins: (int) Number of bins for the histogram.  The default number of bins
            is 64.  The maximum number of bins is 512

    Attributes:
        bins: ([float]) edges of bins
        histogram: ([int]) number of elements falling in each bin
    """

    MAX_LENGTH = 512
    _log_type = "histogram"

    def __init__(
        self,
        sequence = None,
        np_histogram = None,
        num_bins = 64,
    ):

        if np_histogram:
            if len(np_histogram) == 2:
                self.histogram = (
                    np_histogram[0].tolist()
                    if hasattr(np_histogram[0], "tolist")
                    else np_histogram[0]
                )
                self.bins = (
                    np_histogram[1].tolist()
                    if hasattr(np_histogram[1], "tolist")
                    else np_histogram[1]
                )
            else:
                raise ValueError(
                    "Expected np_histogram to be a tuple of (values, bin_edges) or sequence to be specified"
                )
        else:
            np = util.get_module(
                "numpy", required="Auto creation of histograms requires numpy"
            )

            self.histogram, self.bins = np.histogram(sequence, bins=num_bins)
            self.histogram = self.histogram.tolist()
            self.bins = self.bins.tolist()
        if len(self.histogram) > self.MAX_LENGTH:
            raise ValueError(
                "The maximum length of a histogram is %i" % self.MAX_LENGTH
            )
        if len(self.histogram) + 1 != len(self.bins):
            raise ValueError("len(bins) must be len(histogram) + 1")

    def to_json(self, run = None):
        return {"_type": self._log_type, "values": self.histogram, "bins": self.bins}

    def __sizeof__(self):
        """This returns an estimated size in bytes, currently the factor of 1.7
        is used to account for the JSON encoding.  We use this in tb_watcher.TBHistory
        """
        return int((sys.getsizeof(self.histogram) + sys.getsizeof(self.bins)) * 1.7)


class Media(WBValue):
    """A WBValue that we store as a file outside JSON and show in a media panel
    on the front end.

    If necessary, we move or copy the file into the Run's media directory so that it gets
    uploaded.
    """

    # _path: Optional[str]
    # _run: Optional["LocalRun"]
    # _caption: Optional[str]
    # _is_tmp: Optional[bool]
    # _extension: Optional[str]
    # _sha256: Optional[str]
    # _size: Optional[int]

    def __init__(self, caption = None):
        super(Media, self).__init__()
        self._path = None
        # The run under which this object is bound, if any.
        self._run = None
        self._caption = caption

    def _set_file(
        self, path, is_tmp = False, extension = None
    ):
        self._path = path
        self._is_tmp = is_tmp
        self._extension = extension
        if extension is not None and not path.endswith(extension):
            raise ValueError(
                'Media file extension "{}" must occur at the end of path "{}".'.format(
                    extension, path
                )
            )

        with open(self._path, "rb") as f:
            self._sha256 = hashlib.sha256(f.read()).hexdigest()
        self._size = os.path.getsize(self._path)

    @classmethod
    def get_media_subdir(cls):
        raise NotImplementedError

    @staticmethod
    def captions(
        media_items,
    ):
        if media_items[0]._caption is not None:
            return [m._caption for m in media_items]
        else:
            return False

    def is_bound(self):
        return self._run is not None

    def file_is_set(self):
        return self._path is not None and self._sha256 is not None

    def bind_to_run(
        self,
        run,
        key,
        step,
        id_ = None,
    ):
        """Bind this object to a particular Run.

        Calling this function is necessary so that we have somewhere specific to
        put the file associated with this object, from which other Runs can
        refer to it.
        """
        if not self.file_is_set():
            raise AssertionError("bind_to_run called before _set_file")

        # The following two assertions are guaranteed to pass
        # by definition file_is_set, but are needed for
        # mypy to understand that these are strings below.
        assert isinstance(self._path, six.string_types)
        assert isinstance(self._sha256, six.string_types)

        if run is None:
            raise TypeError('Argument "run" must not be None.')
        self._run = run

        # Following assertion required for mypy
        assert self._run is not None

        if self._extension is None:
            _, extension = os.path.splitext(os.path.basename(self._path))
        else:
            extension = self._extension

        if id_ is None:
            id_ = self._sha256[:20]

        file_path = _wb_filename(key, step, id_, extension)
        media_path = os.path.join(self.get_media_subdir(), file_path)
        new_path = os.path.join(self._run.dir, media_path)
        util.mkdir_exists_ok(os.path.dirname(new_path))

        if self._is_tmp:
            shutil.move(self._path, new_path)
            self._path = new_path
            self._is_tmp = False
            _datatypes_callback(media_path)
        else:
            shutil.copy(self._path, new_path)
            self._path = new_path
            _datatypes_callback(media_path)

    def to_json(self, run):
        """Serializes the object into a JSON blob, using a run or artifact to store additional data. If `run_or_artifact`
        is a wandb.Run then `self.bind_to_run()` must have been previously been called.

        Args:
            run_or_artifact (wandb.Run | wandb.Artifact): the Run or Artifact for which this object should be generating
            JSON for - this is useful to to store additional data if needed.

        Returns:
            dict: JSON representation
        """
        # NOTE: uses of Audio in this class are a temporary hack -- when Ref support moves up
        # into Media itself we should get rid of them
        from wandb.data_types import Audio

        json_obj = {}
        if isinstance(run, wandb.wandb_sdk.wandb_run.Run):
            if not self.is_bound():
                raise RuntimeError(
                    "Value of type {} must be bound to a run with bind_to_run() before being serialized to JSON.".format(
                        type(self).__name__
                    )
                )

            assert (
                self._run is run
            ), "We don't support referring to media files across runs."

            # The following two assertions are guaranteed to pass
            # by definition is_bound, but are needed for
            # mypy to understand that these are strings below.
            assert isinstance(self._path, six.string_types)

            json_obj.update(
                {
                    "_type": "file",  # TODO(adrian): This isn't (yet) a real media type we support on the frontend.
                    "path": util.to_forward_slash_path(
                        os.path.relpath(self._path, self._run.dir)
                    ),
                    "sha256": self._sha256,
                    "size": self._size,
                }
            )
            artifact_entry = self._get_artifact_reference_entry()
            if artifact_entry is not None:
                json_obj["artifact_path"] = artifact_entry.ref_url()
        elif isinstance(run, wandb.wandb_sdk.wandb_artifacts.Artifact):
            if self.file_is_set():
                # The following two assertions are guaranteed to pass
                # by definition of the call above, but are needed for
                # mypy to understand that these are strings below.
                assert isinstance(self._path, six.string_types)
                assert isinstance(self._sha256, six.string_types)
                artifact = run  # Checks if the concrete image has already been added to this artifact
                name = artifact.get_added_local_path_name(self._path)
                if name is None:
                    if self._is_tmp:
                        name = os.path.join(
                            self.get_media_subdir(), os.path.basename(self._path)
                        )
                    else:
                        # If the files is not temporary, include the first 8 characters of the file's SHA256 to
                        # avoid name collisions. This way, if there are two images `dir1/img.png` and `dir2/img.png`
                        # we end up with a unique path for each.
                        name = os.path.join(
                            self.get_media_subdir(),
                            self._sha256[:20],
                            os.path.basename(self._path),
                        )

                    # if not, check to see if there is a source artifact for this object
                    if (
                        self._artifact_source
                        is not None
                        # and self._artifact_source.artifact != artifact
                    ):
                        default_root = self._artifact_source.artifact._default_root()
                        # if there is, get the name of the entry (this might make sense to move to a helper off artifact)
                        if self._path.startswith(default_root):
                            name = self._path[len(default_root) :]
                            name = name.lstrip(os.sep)

                        # Add this image as a reference
                        path = self._artifact_source.artifact.get_path(name)
                        artifact.add_reference(path.ref_url(), name=name)
                    elif isinstance(self, Audio) and Audio.path_is_reference(
                        self._path
                    ):
                        artifact.add_reference(self._path, name=name)
                    else:
                        entry = artifact.add_file(
                            self._path, name=name, is_tmp=self._is_tmp
                        )
                        name = entry.path

                json_obj["path"] = name
                json_obj["sha256"] = self._sha256
            json_obj["_type"] = self._log_type
        return json_obj

    @classmethod
    def from_json(
        cls, json_obj, source_artifact
    ):
        """Likely will need to override for any more complicated media objects"""
        return cls(source_artifact.get_path(json_obj["path"]).download())

    def __eq__(self, other):
        """Likely will need to override for any more complicated media objects"""
        return (
            isinstance(other, self.__class__)
            and hasattr(self, "_sha256")
            and hasattr(other, "_sha256")
            and self._sha256 == other._sha256
        )


class BatchableMedia(Media):
    """Parent class for Media we treat specially in batches, like images and
    thumbnails.

    Apart from images, we just use these batches to help organize files by name
    in the media directory.
    """

    def __init__(self):
        super(BatchableMedia, self).__init__()

    @classmethod
    def seq_to_json(
        cls,
        seq,
        run,
        key,
        step,
    ):
        raise NotImplementedError


class Object3D(BatchableMedia):
    """
    Wandb class for 3D point clouds.

    Arguments:
        data_or_path: (numpy array, string, io)
            Object3D can be initialized from a file or a numpy array.

            The file types supported are obj, gltf, babylon, stl.  You can pass a path to
                a file or an io object and a file_type which must be one of `'obj', 'gltf', 'babylon', 'stl'`.

    The shape of the numpy array must be one of either:
    ```python
    [[x y z],       ...] nx3
    [x y z c],     ...] nx4 where c is a category with supported range [1, 14]
    [x y z r g b], ...] nx4 where is rgb is color
    ```
    """

    SUPPORTED_TYPES = set(
        ["obj", "gltf", "glb", "babylon", "stl", "pts.json"]
    )
    _log_type = "object3D-file"

    def __init__(
        self, data_or_path, **kwargs
    ):
        super(Object3D, self).__init__()

        if hasattr(data_or_path, "name"):
            # if the file has a path, we just detect the type and copy it from there
            data_or_path = data_or_path.name  # type: ignore

        if hasattr(data_or_path, "read"):
            if hasattr(data_or_path, "seek"):
                data_or_path.seek(0)  # type: ignore
            object_3d = data_or_path.read()  # type: ignore

            extension = kwargs.pop("file_type", None)
            if extension is None:
                raise ValueError(
                    "Must pass file type keyword argument when using io objects."
                )
            if extension not in Object3D.SUPPORTED_TYPES:
                raise ValueError(
                    "Object 3D only supports numpy arrays or files of the type: "
                    + ", ".join(Object3D.SUPPORTED_TYPES)
                )

            tmp_path = os.path.join(
                _MEDIA_TMP.name, util.generate_id() + "." + extension
            )
            with open(tmp_path, "w") as f:
                f.write(object_3d)

            self._set_file(tmp_path, is_tmp=True)
        elif isinstance(data_or_path, six.string_types):
            path = data_or_path
            extension = None
            for supported_type in Object3D.SUPPORTED_TYPES:
                if path.endswith(supported_type):
                    extension = supported_type
                    break

            if not extension:
                raise ValueError(
                    "File '"
                    + path
                    + "' is not compatible with Object3D: supported types are: "
                    + ", ".join(Object3D.SUPPORTED_TYPES)
                )

            self._set_file(data_or_path, is_tmp=False)
        # Supported different types and scene for 3D scenes
        elif isinstance(data_or_path, dict) and "type" in data_or_path:
            if data_or_path["type"] == "lidar/beta":
                data = {
                    "type": data_or_path["type"],
                    "vectors": data_or_path["vectors"].tolist()
                    if "vectors" in data_or_path
                    else [],
                    "points": data_or_path["points"].tolist()
                    if "points" in data_or_path
                    else [],
                    "boxes": data_or_path["boxes"].tolist()
                    if "boxes" in data_or_path
                    else [],
                }
            else:
                raise ValueError(
                    "Type not supported, only 'lidar/beta' is currently supported"
                )

            tmp_path = os.path.join(_MEDIA_TMP.name, util.generate_id() + ".pts.json")
            json.dump(
                data,
                codecs.open(tmp_path, "w", encoding="utf-8"),
                separators=(",", ":"),
                sort_keys=True,
                indent=4,
            )
            self._set_file(tmp_path, is_tmp=True, extension=".pts.json")
        elif _is_numpy_array(data_or_path):
            np_data = data_or_path

            # The following assertion is required for numpy to trust that
            # np_data is numpy array. The reason it is behind a False
            # guard is to ensure that this line does not run at runtime,
            # which would cause a runtime error if the user's machine did
            # not have numpy installed.

            if wandb.TYPE_CHECKING and TYPE_CHECKING:
                assert isinstance(np_data, np.ndarray)

            if len(np_data.shape) != 2 or np_data.shape[1] not in {3, 4, 6}:
                raise ValueError(
                    """The shape of the numpy array must be one of either
                                    [[x y z],       ...] nx3
                                     [x y z c],     ...] nx4 where c is a category with supported range [1, 14]
                                     [x y z r g b], ...] nx4 where is rgb is color"""
                )

            list_data = np_data.tolist()
            tmp_path = os.path.join(_MEDIA_TMP.name, util.generate_id() + ".pts.json")
            json.dump(
                list_data,
                codecs.open(tmp_path, "w", encoding="utf-8"),
                separators=(",", ":"),
                sort_keys=True,
                indent=4,
            )
            self._set_file(tmp_path, is_tmp=True, extension=".pts.json")
        else:
            raise ValueError("data must be a numpy array, dict or a file object")

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "object3D")

    def to_json(self, run_or_artifact):
        json_dict = super(Object3D, self).to_json(run_or_artifact)
        json_dict["_type"] = Object3D._log_type

        if isinstance(run_or_artifact, wandb.wandb_sdk.wandb_artifacts.Artifact):
            if self._path is None or not self._path.endswith(".pts.json"):
                raise ValueError(
                    "Non-point cloud 3D objects are not yet supported with Artifacts"
                )

        return json_dict

    @classmethod
    def seq_to_json(
        cls,
        seq,
        run,
        key,
        step,
    ):
        seq = list(seq)

        jsons = [obj.to_json(run) for obj in seq]

        for obj in jsons:
            expected = util.to_forward_slash_path(cls.get_media_subdir())
            if not obj["path"].startswith(expected):
                raise ValueError(
                    "Files in an array of Object3D's must be in the {} directory, not {}".format(
                        expected, obj["path"]
                    )
                )

        return {
            "_type": "object3D",
            "filenames": [
                os.path.relpath(j["path"], cls.get_media_subdir()) for j in jsons
            ],
            "count": len(jsons),
            "objects": jsons,
        }


class Molecule(BatchableMedia):
    """
    Wandb class for Molecular data

    Arguments:
        data_or_path: (string, io)
            Molecule can be initialized from a file name or an io object.
    """

    SUPPORTED_TYPES = set(
        ["pdb", "pqr", "mmcif", "mcif", "cif", "sdf", "sd", "gro", "mol2", "mmtf"]
    )
    _log_type = "molecule-file"

    def __init__(self, data_or_path, **kwargs):
        super(Molecule, self).__init__()

        if hasattr(data_or_path, "name"):
            # if the file has a path, we just detect the type and copy it from there
            data_or_path = data_or_path.name  # type: ignore

        if hasattr(data_or_path, "read"):
            if hasattr(data_or_path, "seek"):
                data_or_path.seek(0)  # type: ignore
            molecule = data_or_path.read()  # type: ignore

            extension = kwargs.pop("file_type", None)
            if extension is None:
                raise ValueError(
                    "Must pass file type keyword argument when using io objects."
                )
            if extension not in Molecule.SUPPORTED_TYPES:
                raise ValueError(
                    "Molecule 3D only supports files of the type: "
                    + ", ".join(Molecule.SUPPORTED_TYPES)
                )

            tmp_path = os.path.join(
                _MEDIA_TMP.name, util.generate_id() + "." + extension
            )
            with open(tmp_path, "w") as f:
                f.write(molecule)

            self._set_file(tmp_path, is_tmp=True)
        elif isinstance(data_or_path, six.string_types):
            extension = os.path.splitext(data_or_path)[1][1:]
            if extension not in Molecule.SUPPORTED_TYPES:
                raise ValueError(
                    "Molecule only supports files of the type: "
                    + ", ".join(Molecule.SUPPORTED_TYPES)
                )

            self._set_file(data_or_path, is_tmp=False)
        else:
            raise ValueError("Data must be file name or a file object")

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "molecule")

    def to_json(self, run_or_artifact):
        json_dict = super(Molecule, self).to_json(run_or_artifact)
        json_dict["_type"] = self._log_type
        if self._caption:
            json_dict["caption"] = self._caption
        return json_dict

    @classmethod
    def seq_to_json(
        cls,
        seq,
        run,
        key,
        step,
    ):
        seq = list(seq)

        jsons = [obj.to_json(run) for obj in seq]

        for obj in jsons:
            expected = util.to_forward_slash_path(cls.get_media_subdir())
            if not obj["path"].startswith(expected):
                raise ValueError(
                    "Files in an array of Molecule's must be in the {} directory, not {}".format(
                        cls.get_media_subdir(), obj["path"]
                    )
                )

        return {
            "_type": "molecule",
            "filenames": [obj["path"] for obj in jsons],
            "count": len(jsons),
            "captions": Media.captions(seq),
        }


class Html(BatchableMedia):
    """
    Wandb class for arbitrary html

    Arguments:
        data: (string or io object) HTML to display in wandb
        inject: (boolean) Add a stylesheet to the HTML object.  If set
            to False the HTML will pass through unchanged.
    """

    _log_type = "html-file"

    def __init__(self, data, inject = True):
        super(Html, self).__init__()
        data_is_path = isinstance(data, six.string_types) and os.path.exists(data)
        data_path = ""
        if data_is_path:
            assert isinstance(data, six.string_types)
            data_path = data
            with open(data_path, "r") as file:
                self.html = file.read()
        elif isinstance(data, six.string_types):
            self.html = data
        elif hasattr(data, "read"):
            if hasattr(data, "seek"):
                data.seek(0)
            self.html = data.read()
        else:
            raise ValueError("data must be a string or an io object")

        if inject:
            self.inject_head()

        if inject or not data_is_path:
            tmp_path = os.path.join(_MEDIA_TMP.name, util.generate_id() + ".html")
            with open(tmp_path, "w") as out:
                out.write(self.html)

            self._set_file(tmp_path, is_tmp=True)
        else:
            self._set_file(data_path, is_tmp=False)

    def inject_head(self):
        join = ""
        if "<head>" in self.html:
            parts = self.html.split("<head>", 1)
            parts[0] = parts[0] + "<head>"
        elif "<html>" in self.html:
            parts = self.html.split("<html>", 1)
            parts[0] = parts[0] + "<html><head>"
            parts[1] = "</head>" + parts[1]
        else:
            parts = ["", self.html]
        parts.insert(
            1,
            '<base target="_blank"><link rel="stylesheet" type="text/css" href="https://app.wandb.ai/normalize.css" />',
        )
        self.html = join.join(parts).strip()

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "html")

    def to_json(self, run_or_artifact):
        json_dict = super(Html, self).to_json(run_or_artifact)
        json_dict["_type"] = self._log_type
        return json_dict

    @classmethod
    def from_json(
        cls, json_obj, source_artifact
    ):
        return cls(source_artifact.get_path(json_obj["path"]).download(), inject=False)

    @classmethod
    def seq_to_json(
        cls,
        seq,
        run,
        key,
        step,
    ):
        base_path = os.path.join(run.dir, cls.get_media_subdir())
        util.mkdir_exists_ok(base_path)

        meta = {
            "_type": "html",
            "count": len(seq),
            "html": [h.to_json(run) for h in seq],
        }
        return meta


class Video(BatchableMedia):

    """
    Wandb representation of video.

    Arguments:
        data_or_path: (numpy array, string, io)
            Video can be initialized with a path to a file or an io object.
            The format must be "gif", "mp4", "webm" or "ogg".
            The format must be specified with the format argument.
            Video can be initialized with a numpy tensor.
            The numpy tensor must be either 4 dimensional or 5 dimensional.
            Channels should be (time, channel, height, width) or
            (batch, time, channel, height width)
        caption: (string) caption associated with the video for display
        fps: (int) frames per second for video. Default is 4.
        format: (string) format of video, necessary if initializing with path or io object.
    """

    _log_type = "video-file"
    EXTS = ("gif", "mp4", "webm", "ogg")
    # _width: Optional[int]
    # _height: Optional[int]

    def __init__(
        self,
        data_or_path,
        caption = None,
        fps = 4,
        format = None,
    ):
        super(Video, self).__init__()

        self._fps = fps
        self._format = format or "gif"
        self._width = None
        self._height = None
        self._channels = None
        self._caption = caption
        if self._format not in Video.EXTS:
            raise ValueError("wandb.Video accepts %s formats" % ", ".join(Video.EXTS))

        if isinstance(data_or_path, six.BytesIO):
            filename = os.path.join(
                _MEDIA_TMP.name, util.generate_id() + "." + self._format
            )
            with open(filename, "wb") as f:
                f.write(data_or_path.read())
            self._set_file(filename, is_tmp=True)
        elif isinstance(data_or_path, six.string_types):
            _, ext = os.path.splitext(data_or_path)
            ext = ext[1:].lower()
            if ext not in Video.EXTS:
                raise ValueError(
                    "wandb.Video accepts %s formats" % ", ".join(Video.EXTS)
                )
            self._set_file(data_or_path, is_tmp=False)
            # ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 data_or_path
        else:
            if hasattr(data_or_path, "numpy"):  # TF data eager tensors
                self.data = data_or_path.numpy()  # type: ignore
            elif _is_numpy_array(data_or_path):
                self.data = data_or_path
            else:
                raise ValueError(
                    "wandb.Video accepts a file path or numpy like data as input"
                )
            self.encode()

    def encode(self):
        mpy = util.get_module(
            "moviepy.editor",
            required='wandb.Video requires moviepy and imageio when passing raw data.  Install with "pip install moviepy imageio"',
        )
        tensor = self._prepare_video(self.data)
        _, self._height, self._width, self._channels = tensor.shape

        # encode sequence of images into gif string
        clip = mpy.ImageSequenceClip(list(tensor), fps=self._fps)

        filename = os.path.join(
            _MEDIA_TMP.name, util.generate_id() + "." + self._format
        )
        if wandb.TYPE_CHECKING and TYPE_CHECKING:
            kwargs = {}
        try:  # older versions of moviepy do not support logger argument
            kwargs = {"logger": None}
            if self._format == "gif":
                clip.write_gif(filename, **kwargs)
            else:
                clip.write_videofile(filename, **kwargs)
        except TypeError:
            try:  # even older versions of moviepy do not support progress_bar argument
                kwargs = {"verbose": False, "progress_bar": False}
                if self._format == "gif":
                    clip.write_gif(filename, **kwargs)
                else:
                    clip.write_videofile(filename, **kwargs)
            except TypeError:
                kwargs = {
                    "verbose": False,
                }
                if self._format == "gif":
                    clip.write_gif(filename, **kwargs)
                else:
                    clip.write_videofile(filename, **kwargs)
        self._set_file(filename, is_tmp=True)

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "videos")

    def to_json(self, run_or_artifact):
        json_dict = super(Video, self).to_json(run_or_artifact)
        json_dict["_type"] = self._log_type

        if self._width is not None:
            json_dict["width"] = self._width
        if self._height is not None:
            json_dict["height"] = self._height
        if self._caption:
            json_dict["caption"] = self._caption

        return json_dict

    def _prepare_video(self, video):
        """This logic was mostly taken from tensorboardX"""
        np = util.get_module(
            "numpy",
            required='wandb.Video requires numpy when passing raw data. To get it, run "pip install numpy".',
        )
        if video.ndim < 4:
            raise ValueError(
                "Video must be atleast 4 dimensions: time, channels, height, width"
            )
        if video.ndim == 4:
            video = video.reshape(1, *video.shape)
        b, t, c, h, w = video.shape

        if video.dtype != np.uint8:
            logging.warning("Converting video data to uint8")
            video = video.astype(np.uint8)

        def is_power2(num):
            return num != 0 and ((num & (num - 1)) == 0)

        # pad to nearest power of 2, all at once
        if not is_power2(video.shape[0]):
            len_addition = int(2 ** video.shape[0].bit_length() - video.shape[0])
            video = np.concatenate(
                (video, np.zeros(shape=(len_addition, t, c, h, w))), axis=0
            )

        n_rows = 2 ** ((b.bit_length() - 1) // 2)
        n_cols = video.shape[0] // n_rows

        video = np.reshape(video, newshape=(n_rows, n_cols, t, c, h, w))
        video = np.transpose(video, axes=(2, 0, 4, 1, 5, 3))
        video = np.reshape(video, newshape=(t, n_rows * h, n_cols * w, c))
        return video

    @classmethod
    def seq_to_json(
        cls,
        seq,
        run,
        key,
        step,
    ):
        base_path = os.path.join(run.dir, cls.get_media_subdir())
        util.mkdir_exists_ok(base_path)

        meta = {
            "_type": "videos",
            "count": len(seq),
            "videos": [v.to_json(run) for v in seq],
            "captions": Video.captions(seq),
        }
        return meta


# Allows encoding of arbitrary JSON structures
# as a file
#
# This class should be used as an abstract class
# extended to have validation methods


class JSONMetadata(Media):
    """
    JSONMetadata is a type for encoding arbitrary metadata as files.
    """

    def __init__(self, val):
        super(JSONMetadata, self).__init__()

        self.validate(val)
        self._val = val

        ext = "." + self.type_name() + ".json"
        tmp_path = os.path.join(_MEDIA_TMP.name, util.generate_id() + ext)
        util.json_dump_uncompressed(
            self._val, codecs.open(tmp_path, "w", encoding="utf-8")
        )
        self._set_file(tmp_path, is_tmp=True, extension=ext)

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "metadata", cls.type_name())

    def to_json(self, run_or_artifact):
        json_dict = super(JSONMetadata, self).to_json(run_or_artifact)
        json_dict["_type"] = self.type_name()

        return json_dict

    # These methods should be overridden in the child class
    @classmethod
    def type_name(cls):
        return "metadata"

    def validate(self, val):
        return True


class ImageMask(Media):
    """
    Wandb class for image masks or overlays, useful for tasks like semantic segmentation.

    Arguments:
        val: (dictionary)
            One of these two keys to represent the image:
                mask_data : (2D numpy array) The mask containing an integer class label
                    for each pixel in the image
                path : (string) The path to a saved image file of the mask
            class_labels : (dictionary of integers to strings, optional) A mapping of the
                integer class labels in the mask to readable class names. These will default
                to class_0, class_1, class_2, etc.

        key: (string)
            The readable name or id for this mask type (e.g. predictions, ground_truth)

    Examples:
        Log a mask overlay for a given image
        ```python
        predicted_mask = np.array([[1, 2, 2, ... , 3, 2, 1], ...])
        ground_truth_mask = np.array([[1, 1, 1, ... , 2, 3, 1], ...])

        class_labels = {
            0: "person",
            1: "tree",
            2: "car",
            3: "road"
        }

        masked_image = wandb.Image(image, masks={
            "predictions": {
                "mask_data": predicted_mask,
                "class_labels": class_labels
            },
            "ground_truth": {
                "mask_data": ground_truth_mask,
                "class_labels": class_labels
            }
        }
        wandb.log({"img_with_masks" : masked_image})
        ```

        Prepare an image mask to be added to a wandb.Table
        ```python
        raw_image_path = "sample_image.png"
        predicted_mask_path = "predicted_mask.png"
        class_set = wandb.Classes([
            {"name" : "person", "id" : 0},
            {"name" : "tree", "id" : 1},
            {"name" : "car", "id" : 2},
            {"name" : "road", "id" : 3}
        ])
        masked_image = wandb.Image(raw_image_path, classes=class_set,
            masks={"prediction" : {"path" : predicted_mask_path}})
        ```
    """

    _log_type = "mask"

    def __init__(self, val, key):
        """
        Arguments:
            val: (dictionary)
                One of these two keys to represent the image:
                    mask_data : (2D numpy array) The mask containing an integer class label
                        for each pixel in the image
                    path : (string) The path to a saved image file of the mask
                class_labels : (dictionary of integers to strings, optional) A mapping of the
                    integer class labels in the mask to readable class names. These will default
                    to class_0, class_1, class_2, etc.

            key: (string)
                The readable name or id for this mask type (e.g. predictions, ground_truth)
        """
        super(ImageMask, self).__init__()

        if "path" in val:
            self._set_file(val["path"])
        else:
            np = util.get_module("numpy", required="Image mask support requires numpy")
            # Add default class mapping
            if "class_labels" not in val:
                classes = np.unique(val["mask_data"]).astype(np.int32).tolist()
                class_labels = dict((c, "class_" + str(c)) for c in classes)
                val["class_labels"] = class_labels

            self.validate(val)
            self._val = val
            self._key = key

            ext = "." + self.type_name() + ".png"
            tmp_path = os.path.join(_MEDIA_TMP.name, util.generate_id() + ext)

            pil_image = util.get_module(
                "PIL.Image",
                required='wandb.Image needs the PIL package. To get it, run "pip install pillow".',
            )
            image = pil_image.fromarray(val["mask_data"].astype(np.int8), mode="L")

            image.save(tmp_path, transparency=None)
            self._set_file(tmp_path, is_tmp=True, extension=ext)

    def bind_to_run(
        self,
        run,
        key,
        step,
        id_ = None,
    ):
        # bind_to_run key argument is the Image parent key
        # the self._key value is the mask's sub key
        super(ImageMask, self).bind_to_run(run, key, step, id_=id_)
        class_labels = self._val["class_labels"]

        run._add_singleton(
            "mask/class_labels",
            str(key) + "_wandb_delimeter_" + self._key,
            class_labels,
        )

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "images", cls.type_name())

    @classmethod
    def from_json(
        cls, json_obj, source_artifact
    ):
        return cls(
            {"path": source_artifact.get_path(json_obj["path"]).download()}, key="",
        )

    def to_json(self, run_or_artifact):
        json_dict = super(ImageMask, self).to_json(run_or_artifact)

        if isinstance(run_or_artifact, wandb.wandb_sdk.wandb_run.Run):
            json_dict["_type"] = self.type_name()
            return json_dict
        elif isinstance(run_or_artifact, wandb.wandb_sdk.wandb_artifacts.Artifact):
            # Nothing special to add (used to add "digest", but no longer used.)
            return json_dict
        else:
            raise ValueError("to_json accepts wandb_run.Run or wandb_artifact.Artifact")

    @classmethod
    def type_name(cls):
        return cls._log_type

    def validate(self, val):
        np = util.get_module("numpy", required="Image mask support requires numpy")
        # 2D Make this work with all tensor(like) types
        if "mask_data" not in val:
            raise TypeError(
                'Missing key "mask_data": An image mask requires mask data: a 2D array representing the predictions'
            )
        else:
            error_str = "mask_data must be a 2D array"
            shape = val["mask_data"].shape
            if len(shape) != 2:
                raise TypeError(error_str)
            if not (
                (val["mask_data"] >= 0).all() and (val["mask_data"] <= 255).all()
            ) and issubclass(val["mask_data"].dtype.type, np.integer):
                raise TypeError("Mask data must be integers between 0 and 255")

        # Optional argument
        if "class_labels" in val:
            for k, v in list(val["class_labels"].items()):
                if (not isinstance(k, numbers.Number)) or (
                    not isinstance(v, six.string_types)
                ):
                    raise TypeError(
                        "Class labels must be a dictionary of numbers to strings"
                    )
        return True


class BoundingBoxes2D(JSONMetadata):
    """
    Wandb class for logging 2D bounding boxes on images, useful for tasks like object detection

    Arguments:
        val: (dictionary) A dictionary of the following form:
            box_data: (list of dictionaries) One dictionary for each bounding box, containing:
                position: (dictionary) the position and size of the bounding box, in one of two formats
                    Note that boxes need not all use the same format.
                    {"minX", "minY", "maxX", "maxY"}: (dictionary) A set of coordinates defining
                        the upper and lower bounds of the box (the bottom left and top right corners)
                    {"middle", "width", "height"}: (dictionary) A set of coordinates defining the
                        center and dimensions of the box, with "middle" as a list [x, y] for the
                        center point and "width" and "height" as numbers
                domain: (string) One of two options for the bounding box coordinate domain
                    null: By default, or if no argument is passed, the coordinate domain
                        is assumed to be relative to the original image, expressing this box as a fraction
                        or percentage of the original image. This means all coordinates and dimensions
                        passed into the "position" argument are floating point numbers between 0 and 1.
                    "pixel": (string literal) The coordinate domain is set to the pixel space. This means all
                        coordinates and dimensions passed into "position" are integers within the bounds
                        of the image dimensions.
                class_id: (integer) The class label id for this box
                scores: (dictionary of string to number, optional) A mapping of named fields
                        to numerical values (float or int), can be used for filtering boxes in the UI
                        based on a range of values for the corresponding field
                box_caption: (string, optional) A string to be displayed as the label text above this
                        box in the UI, often composed of the class label, class name, and/or scores

            class_labels: (dictionary, optional) A map of integer class labels to their readable class names

        key: (string)
            The readable name or id for this set of bounding boxes (e.g. predictions, ground_truth)

    Examples:
        Log a set of predicted and ground truth bounding boxes for a given image
        ```python
        class_labels = {
            0: "person",
            1: "car",
            2: "road",
            3: "building"
        }
        img = wandb.Image(image, boxes={
            "predictions": {
                "box_data": [
                    {
                        # one box expressed in the default relative/fractional domain
                        "position": {
                            "minX": 0.1,
                            "maxX": 0.2,
                            "minY": 0.3,
                            "maxY": 0.4
                        },
                        "class_id" : 1,
                        "box_caption": class_labels[1],
                        "scores" : {
                            "acc": 0.2,
                            "loss": 1.2
                        }
                    },
                    {
                        # another box expressed in the pixel domain
                        "position": {
                            "middle": [150, 20],
                            "width": 68,
                            "height": 112
                        },
                        "domain" : "pixel",
                        "class_id" : 3,
                        "box_caption": "a building",
                        "scores" : {
                            "acc": 0.5,
                            "loss": 0.7
                        }
                    },
                    ...
                    # Log as many boxes an as needed
                ],
                "class_labels": class_labels
            },
            # Log each meaningful group of boxes with a unique key name
            "ground_truth": {
            ...
            }
        })

        wandb.log({"driving_scene": img})
        ```

        Prepare an image with bounding boxes to be added to a wandb.Table
        ```python
        raw_image_path = "sample_image.png"

        class_set = wandb.Classes([
            {"name" : "person", "id" : 0},
            {"name" : "car", "id" : 1},
            {"name" : "road", "id" : 2},
            {"name" : "building", "id" : 3}
        ])

        image_with_boxes = wandb.Image(raw_image_path, classes=class_set,
            boxes=[...identical to previous example...])
        ```
    """

    _log_type = "bounding-boxes"
    # TODO: when the change is made to have this produce a dict with a _type, define
    # it here as _log_type, associate it in to_json

    def __init__(self, val, key):
        """
        Arguments:
            val: (dictionary) A dictionary of the following form:
                box_data: (list of dictionaries) One dictionary for each bounding box, containing:
                    position: (dictionary) the position and size of the bounding box, in one of two formats
                        Note that boxes need not all use the same format.
                        {"minX", "minY", "maxX", "maxY"}: (dictionary) A set of coordinates defining
                            the upper and lower bounds of the box (the bottom left and top right corners)
                        {"middle", "width", "height"}: (dictionary) A set of coordinates defining the
                            center and dimensions of the box, with "middle" as a list [x, y] for the
                            center point and "width" and "height" as numbers
                    domain: (string) One of two options for the bounding box coordinate domain
                        null: By default, or if no argument is passed, the coordinate domain
                            is assumed to be relative to the original image, expressing this box as a fraction
                            or percentage of the original image. This means all coordinates and dimensions
                            passed into the "position" argument are floating point numbers between 0 and 1.
                        "pixel": (string literal) The coordinate domain is set to the pixel space. This means all
                            coordinates and dimensions passed into "position" are integers within the bounds
                            of the image dimensions.
                    class_id: (integer) The class label id for this box
                    scores: (dictionary of string to number, optional) A mapping of named fields
                            to numerical values (float or int), can be used for filtering boxes in the UI
                            based on a range of values for the corresponding field
                    box_caption: (string, optional) A string to be displayed as the label text above this
                            box in the UI, often composed of the class label, class name, and/or scores

                class_labels: (dictionary, optional) A map of integer class labels to their readable class names

            key: (string)
                The readable name or id for this set of bounding boxes (e.g. predictions, ground_truth)
        """
        super(BoundingBoxes2D, self).__init__(val)
        self._val = val["box_data"]
        self._key = key
        # Add default class mapping
        if "class_labels" not in val:
            np = util.get_module(
                "numpy", required="Bounding box support requires numpy"
            )
            classes = (
                np.unique(list([box["class_id"] for box in val["box_data"]]))
                .astype(np.int32)
                .tolist()
            )
            class_labels = dict((c, "class_" + str(c)) for c in classes)
            self._class_labels = class_labels
        else:
            self._class_labels = val["class_labels"]

    def bind_to_run(
        self,
        run,
        key,
        step,
        id_ = None,
    ):
        # bind_to_run key argument is the Image parent key
        # the self._key value is the mask's sub key
        super(BoundingBoxes2D, self).bind_to_run(run, key, step, id_=id_)
        run._add_singleton(
            "bounding_box/class_labels",
            str(key) + "_wandb_delimeter_" + self._key,
            self._class_labels,
        )

    @classmethod
    def type_name(cls):
        return "boxes2D"

    def validate(self, val):
        # Optional argument
        if "class_labels" in val:
            for k, v in list(val["class_labels"].items()):
                if (not isinstance(k, numbers.Number)) or (
                    not isinstance(v, six.string_types)
                ):
                    raise TypeError(
                        "Class labels must be a dictionary of numbers to string"
                    )

        boxes = val["box_data"]
        if not isinstance(boxes, list):
            raise TypeError("Boxes must be a list")

        for box in boxes:
            # Required arguments
            error_str = "Each box must contain a position with: middle, width, and height or \
                    \nminX, maxX, minY, maxY."
            if "position" not in box:
                raise TypeError(error_str)
            else:
                valid = False
                if (
                    "middle" in box["position"]
                    and len(box["position"]["middle"]) == 2
                    and has_num(box["position"], "width")
                    and has_num(box["position"], "height")
                ):
                    valid = True
                elif (
                    has_num(box["position"], "minX")
                    and has_num(box["position"], "maxX")
                    and has_num(box["position"], "minY")
                    and has_num(box["position"], "maxY")
                ):
                    valid = True

                if not valid:
                    raise TypeError(error_str)

            # Optional arguments
            if ("scores" in box) and not isinstance(box["scores"], dict):
                raise TypeError("Box scores must be a dictionary")
            elif "scores" in box:
                for k, v in list(box["scores"].items()):
                    if not isinstance(k, six.string_types):
                        raise TypeError("A score key must be a string")
                    if not isinstance(v, numbers.Number):
                        raise TypeError("A score value must be a number")

            if ("class_id" in box) and not isinstance(
                box["class_id"], six.integer_types
            ):
                raise TypeError("A box's class_id must be an integer")

            # Optional
            if ("box_caption" in box) and not isinstance(
                box["box_caption"], six.string_types
            ):
                raise TypeError("A box's caption must be a string")
        return True

    def to_json(self, run_or_artifact):

        if isinstance(run_or_artifact, wandb.wandb_sdk.wandb_run.Run):
            return super(BoundingBoxes2D, self).to_json(run_or_artifact)
        elif isinstance(run_or_artifact, wandb.wandb_sdk.wandb_artifacts.Artifact):
            # TODO (tim): I would like to log out a proper dictionary representing this object, but don't
            # want to mess with the visualizations that are currently available in the UI. This really should output
            # an object with a _type key. Will need to push this change to the UI first to ensure backwards compat
            return self._val
        else:
            raise ValueError("to_json accepts wandb_run.Run or wandb_artifact.Artifact")

    @classmethod
    def from_json(
        cls, json_obj, source_artifact
    ):
        return cls({"box_data": json_obj}, "")


class Classes(Media):
    _log_type = "classes"

    # _class_set: Sequence[dict]

    def __init__(self, class_set):
        """Classes is holds class metadata intended to be used in concert with other objects when visualizing artifacts

        Args:
            class_set (list): list of dicts in the form of {"id":int|str, "name":str}
        """
        super(Classes, self).__init__()
        for class_obj in class_set:
            assert "id" in class_obj and "name" in class_obj
        self._class_set = class_set

    @classmethod
    def from_json(
        cls,
        json_obj,
        source_artifact,
    ):
        return cls(json_obj.get("class_set"))  # type: ignore

    def to_json(
        self, run_or_artifact
    ):
        json_obj = {}
        # This is a bit of a hack to allow _ClassesIdType to
        # be able to operate fully without an artifact in play.
        # In all other cases, artifact should be a true artifact.
        if run_or_artifact is not None:
            json_obj = super(Classes, self).to_json(run_or_artifact)
        json_obj["_type"] = Classes._log_type
        json_obj["class_set"] = self._class_set
        return json_obj

    def get_type(self):
        return _ClassesIdType(self)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        if isinstance(other, Classes):
            return self._class_set == other._class_set
        else:
            return False


class Image(BatchableMedia):
    """
    Wandb class for images.

    Arguments:
        data_or_path: (numpy array, string, io) Accepts numpy array of
            image data, or a PIL image. The class attempts to infer
            the data format and converts it.
        mode: (string) The PIL mode for an image. Most common are "L", "RGB",
            "RGBA". Full explanation at https://pillow.readthedocs.io/en/4.2.x/handbook/concepts.html#concept-modes.
        caption: (string) Label for display of image.
    """

    MAX_ITEMS = 108

    # PIL limit
    MAX_DIMENSION = 65500

    _log_type = "image-file"

    # format: Optional[str]
    # _grouping: Optional[str]
    # _caption: Optional[str]
    # _width: Optional[int]
    # _height: Optional[int]
    # _image: Optional["PIL.Image"]
    # _classes: Optional["Classes"]
    # _boxes: Optional[Dict[str, "BoundingBoxes2D"]]
    # _masks: Optional[Dict[str, "ImageMask"]]

    def __init__(
        self,
        data_or_path,
        mode = None,
        caption = None,
        grouping = None,
        classes = None,
        boxes = None,
        masks = None,
    ):
        super(Image, self).__init__()
        # TODO: We should remove grouping, it's a terrible name and I don't
        # think anyone uses it.

        self._grouping = None
        self._caption = None
        self._width = None
        self._height = None
        self._image = None
        self._classes = None
        self._boxes = None
        self._masks = None

        # Allows the user to pass an Image object as the first parameter and have a perfect copy,
        # only overriding additional metdata passed in. If this pattern is compelling, we can generalize.
        if isinstance(data_or_path, Image):
            self._initialize_from_wbimage(data_or_path)
        elif isinstance(data_or_path, six.string_types):
            self._initialize_from_path(data_or_path)
        else:
            self._initialize_from_data(data_or_path, mode)

        self._set_initialization_meta(grouping, caption, classes, boxes, masks)

    def _set_initialization_meta(
        self,
        grouping = None,
        caption = None,
        classes = None,
        boxes = None,
        masks = None,
    ):
        if grouping is not None:
            self._grouping = grouping

        if caption is not None:
            self._caption = caption

        if classes is not None:
            if not isinstance(classes, Classes):
                self._classes = Classes(classes)
            else:
                self._classes = classes

        if boxes:
            if not isinstance(boxes, dict):
                raise ValueError('Images "boxes" argument must be a dictionary')
            boxes_final = {}
            for key in boxes:
                box_item = boxes[key]
                if isinstance(box_item, BoundingBoxes2D):
                    boxes_final[key] = box_item
                elif isinstance(box_item, dict):
                    boxes_final[key] = BoundingBoxes2D(box_item, key)
            self._boxes = boxes_final

        if masks:
            if not isinstance(masks, dict):
                raise ValueError('Images "masks" argument must be a dictionary')
            masks_final = {}
            for key in masks:
                mask_item = masks[key]
                if isinstance(mask_item, ImageMask):
                    masks_final[key] = mask_item
                elif isinstance(mask_item, dict):
                    masks_final[key] = ImageMask(mask_item, key)
            self._masks = masks_final

        self._width, self._height = self._image.size  # type: ignore

    def _initialize_from_wbimage(self, wbimage):
        self._grouping = wbimage._grouping
        self._caption = wbimage._caption
        self._width = wbimage._width
        self._height = wbimage._height
        self._image = wbimage._image
        self._classes = wbimage._classes
        self._path = wbimage._path
        self._is_tmp = wbimage._is_tmp
        self._extension = wbimage._extension
        self._sha256 = wbimage._sha256
        self._size = wbimage._size
        self.format = wbimage.format
        self._artifact_source = wbimage._artifact_source
        self._artifact_target = wbimage._artifact_target

        # We do not want to implicitly copy boxes or masks, just the image-related data.
        # self._boxes = wbimage._boxes
        # self._masks = wbimage._masks

    def _initialize_from_path(self, path):
        pil_image = util.get_module(
            "PIL.Image",
            required='wandb.Image needs the PIL package. To get it, run "pip install pillow".',
        )
        self._set_file(path, is_tmp=False)
        self._image = pil_image.open(path)
        self._image.load()
        ext = os.path.splitext(path)[1][1:]
        self.format = ext

    def _initialize_from_data(self, data, mode = None,):
        pil_image = util.get_module(
            "PIL.Image",
            required='wandb.Image needs the PIL package. To get it, run "pip install pillow".',
        )
        if util.is_matplotlib_typename(util.get_full_typename(data)):
            buf = six.BytesIO()
            util.ensure_matplotlib_figure(data).savefig(buf)
            self._image = pil_image.open(buf)
        elif isinstance(data, pil_image.Image):
            self._image = data
        elif util.is_pytorch_tensor_typename(util.get_full_typename(data)):
            vis_util = util.get_module(
                "torchvision.utils", "torchvision is required to render images"
            )
            if hasattr(data, "requires_grad") and data.requires_grad:
                data = data.detach()
            data = vis_util.make_grid(data, normalize=True)
            self._image = pil_image.fromarray(
                data.mul(255).clamp(0, 255).byte().permute(1, 2, 0).cpu().numpy()
            )
        else:
            if hasattr(data, "numpy"):  # TF data eager tensors
                data = data.numpy()
            if data.ndim > 2:
                data = data.squeeze()  # get rid of trivial dimensions as a convenience
            self._image = pil_image.fromarray(
                self.to_uint8(data), mode=mode or self.guess_mode(data)
            )

        tmp_path = os.path.join(_MEDIA_TMP.name, util.generate_id() + ".png")
        self.format = "png"
        self._image.save(tmp_path, transparency=None)
        self._set_file(tmp_path, is_tmp=True)

    @classmethod
    def from_json(
        cls, json_obj, source_artifact
    ):
        classes = None
        if json_obj.get("classes") is not None:
            classes = source_artifact.get(json_obj["classes"]["path"])

        masks = json_obj.get("masks")
        _masks = None
        if masks:
            _masks = {}
            for key in masks:
                _masks[key] = ImageMask.from_json(masks[key], source_artifact)
                _masks[key]._set_artifact_source(source_artifact)
                _masks[key]._key = key

        boxes = json_obj.get("boxes")
        _boxes = None
        if boxes:
            _boxes = {}
            for key in boxes:
                _boxes[key] = BoundingBoxes2D.from_json(boxes[key], source_artifact)
                _boxes[key]._key = key

        return cls(
            source_artifact.get_path(json_obj["path"]).download(),
            caption=json_obj.get("caption"),
            grouping=json_obj.get("grouping"),
            classes=classes,
            boxes=_boxes,
            masks=_masks,
        )

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "images")

    def bind_to_run(
        self,
        run,
        key,
        step,
        id_ = None,
    ):
        super(Image, self).bind_to_run(run, key, step, id_)
        if self._boxes is not None:
            for i, k in enumerate(self._boxes):
                id_ = "{}{}".format(id_, i) if id_ is not None else None
                self._boxes[k].bind_to_run(run, key, step, id_)

        if self._masks is not None:
            for i, k in enumerate(self._masks):
                id_ = "{}{}".format(id_, i) if id_ is not None else None
                self._masks[k].bind_to_run(run, key, step, id_)

    def to_json(self, run_or_artifact):
        json_dict = super(Image, self).to_json(run_or_artifact)
        json_dict["_type"] = Image._log_type
        json_dict["format"] = self.format

        if self._width is not None:
            json_dict["width"] = self._width
        if self._height is not None:
            json_dict["height"] = self._height
        if self._grouping:
            json_dict["grouping"] = self._grouping
        if self._caption:
            json_dict["caption"] = self._caption

        if isinstance(run_or_artifact, wandb.wandb_sdk.wandb_artifacts.Artifact):
            artifact = run_or_artifact
            if (
                self._masks is not None or self._boxes is not None
            ) and self._classes is None:
                raise ValueError(
                    "classes must be passed to wandb.Image which have masks or bounding boxes when adding to artifacts"
                )

            if self._classes is not None:
                # Here, rather than give each class definition it's own name (and entry), we
                # purposely are giving a non-unique class name of /media/cls.classes.json.
                # This may create user confusion if if multiple different class definitions
                # are expected in a single artifact. However, we want to catch this user pattern
                # if it exists and dive deeper. The alternative code is provided below.
                #
                class_name = os.path.join("media", "cls")
                #
                # class_name = os.path.join(
                #     "media", "classes", os.path.basename(self._path) + "_cls"
                # )
                #
                classes_entry = artifact.add(self._classes, class_name)
                json_dict["classes"] = {
                    "type": "classes-file",
                    "path": classes_entry.path,
                    "digest": classes_entry.digest,
                }

        elif not isinstance(run_or_artifact, wandb.wandb_sdk.wandb_run.Run):
            raise ValueError("to_json accepts wandb_run.Run or wandb_artifact.Artifact")

        if self._boxes:
            json_dict["boxes"] = {
                k: box.to_json(run_or_artifact) for (k, box) in self._boxes.items()
            }
        if self._masks:
            json_dict["masks"] = {
                k: mask.to_json(run_or_artifact) for (k, mask) in self._masks.items()
            }
        return json_dict

    def guess_mode(self, data):
        """
        Guess what type of image the np.array is representing
        """
        # TODO: do we want to support dimensions being at the beginning of the array?
        if data.ndim == 2:
            return "L"
        elif data.shape[-1] == 3:
            return "RGB"
        elif data.shape[-1] == 4:
            return "RGBA"
        else:
            raise ValueError(
                "Un-supported shape for image conversion %s" % list(data.shape)
            )

    @classmethod
    def to_uint8(cls, data):
        """
        Converts floating point image on the range [0,1] and integer images
        on the range [0,255] to uint8, clipping if necessary.
        """
        np = util.get_module(
            "numpy",
            required="wandb.Image requires numpy if not supplying PIL Images: pip install numpy",
        )

        # I think it's better to check the image range vs the data type, since many
        # image libraries will return floats between 0 and 255

        # some images have range -1...1 or 0-1
        dmin = np.min(data)
        if dmin < 0:
            data = (data - np.min(data)) / np.ptp(data)
        if np.max(data) <= 1.0:
            data = (data * 255).astype(np.int32)

        # assert issubclass(data.dtype.type, np.integer), 'Illegal image format.'
        return data.clip(0, 255).astype(np.uint8)

    @classmethod
    def seq_to_json(
        cls,
        seq,
        run,
        key,
        step,
    ):
        """
        Combines a list of images into a meta dictionary object describing the child images.
        """
        if wandb.TYPE_CHECKING and TYPE_CHECKING:
            seq = cast(Sequence["Image"], seq)

        jsons = [obj.to_json(run) for obj in seq]

        media_dir = cls.get_media_subdir()

        for obj in jsons:
            expected = util.to_forward_slash_path(media_dir)
            if not obj["path"].startswith(expected):
                raise ValueError(
                    "Files in an array of Image's must be in the {} directory, not {}".format(
                        cls.get_media_subdir(), obj["path"]
                    )
                )

        num_images_to_log = len(seq)
        width, height = seq[0]._image.size  # type: ignore
        format = jsons[0]["format"]

        def size_equals_image(image):
            img_width, img_height = image._image.size  # type: ignore
            return img_width == width and img_height == height  # type: ignore

        sizes_match = all(size_equals_image(img) for img in seq)
        if not sizes_match:
            logging.warning(
                "Images sizes do not match. This will causes images to be display incorrectly in the UI."
            )

        meta = {
            "_type": "images/separated",
            "width": width,
            "height": height,
            "format": format,
            "count": num_images_to_log,
        }

        captions = Image.all_captions(seq)

        if captions:
            meta["captions"] = captions

        all_masks = Image.all_masks(seq, run, key, step)

        if all_masks:
            meta["all_masks"] = all_masks

        all_boxes = Image.all_boxes(seq, run, key, step)

        if all_boxes:
            meta["all_boxes"] = all_boxes

        return meta

    @classmethod
    def all_masks(
        cls,
        images,
        run,
        run_key,
        step,
    ):
        all_mask_groups = []
        for image in images:
            if image._masks:
                mask_group = {}
                for k in image._masks:
                    mask = image._masks[k]
                    mask_group[k] = mask.to_json(run)
                all_mask_groups.append(mask_group)
            else:
                all_mask_groups.append(None)
        if all_mask_groups and not all(x is None for x in all_mask_groups):
            return all_mask_groups
        else:
            return False

    @classmethod
    def all_boxes(
        cls,
        images,
        run,
        run_key,
        step,
    ):
        all_box_groups = []
        for image in images:
            if image._boxes:
                box_group = {}
                for k in image._boxes:
                    box = image._boxes[k]
                    box_group[k] = box.to_json(run)
                all_box_groups.append(box_group)
            else:
                all_box_groups.append(None)
        if all_box_groups and not all(x is None for x in all_box_groups):
            return all_box_groups
        else:
            return False

    @classmethod
    def all_captions(
        cls, images
    ):
        return cls.captions(images)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        if not isinstance(other, Image):
            return False
        else:
            return (
                self._grouping == other._grouping
                and self._caption == other._caption
                and self._width == other._width
                and self._height == other._height
                and self._image == other._image
                and self._classes == other._classes
            )

    def to_data_array(self):
        res = []
        if self._image is not None:
            data = list(self._image.getdata())
            for i in range(self._image.height):
                res.append(data[i * self._image.width : (i + 1) * self._image.width])
        return res


class Plotly(Media):
    """
    Wandb class for plotly plots.

    Arguments:
        val: matplotlib or plotly figure
    """

    _log_type = "plotly-file"

    @classmethod
    def make_plot_media(
        cls, val
    ):
        if util.is_matplotlib_typename(util.get_full_typename(val)):
            if util.matplotlib_contains_images(val):
                return Image(val)
            val = util.matplotlib_to_plotly(val)
        return cls(val)

    def __init__(self, val):
        super(Plotly, self).__init__()
        # First, check to see if the incoming `val` object is a plotfly figure
        if not util.is_plotly_figure_typename(util.get_full_typename(val)):
            # If it is not, but it is a matplotlib figure, then attempt to convert it to plotly
            if util.is_matplotlib_typename(util.get_full_typename(val)):
                if util.matplotlib_contains_images(val):
                    raise ValueError(
                        "Plotly does not currently support converting matplotlib figures containing images. \
                            You can convert the plot to a static image with `wandb.Image(plt)` "
                    )
                val = util.matplotlib_to_plotly(val)
            else:
                raise ValueError(
                    "Logged plots must be plotly figures, or matplotlib plots convertible to plotly via mpl_to_plotly"
                )

        tmp_path = os.path.join(_MEDIA_TMP.name, util.generate_id() + ".plotly.json")
        val = _numpy_arrays_to_lists(val.to_plotly_json())
        util.json_dump_safer(val, codecs.open(tmp_path, "w", encoding="utf-8"))
        self._set_file(tmp_path, is_tmp=True, extension=".plotly.json")

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "plotly")

    def to_json(self, run_or_artifact):
        json_dict = super(Plotly, self).to_json(run_or_artifact)
        json_dict["_type"] = self._log_type
        return json_dict


def history_dict_to_json(
    run, payload, step = None
):
    # Converts a History row dict's elements so they're friendly for JSON serialization.

    if step is None:
        # We should be at the top level of the History row; assume this key is set.
        step = payload["_step"]

    # We use list here because we were still seeing cases of RuntimeError dict changed size
    for key in list(payload):
        val = payload[key]
        if isinstance(val, dict):
            payload[key] = history_dict_to_json(run, val, step=step)
        else:
            payload[key] = val_to_json(run, key, val, namespace=step)

    return payload


# TODO: refine this
def val_to_json(
    run,
    key,
    val,
    namespace = None,
):
    # Converts a wandb datatype to its JSON representation.
    if namespace is None:
        raise ValueError(
            "val_to_json must be called with a namespace(a step number, or 'summary') argument"
        )

    converted = val
    typename = util.get_full_typename(val)

    if util.is_pandas_data_frame(val):
        raise ValueError(
            "We do not support DataFrames in the Summary or History. Try run.log({{'{}': wandb.Table(dataframe=df)}})".format(
                key
            )
        )
    elif util.is_matplotlib_typename(typename) or util.is_plotly_typename(typename):
        val = Plotly.make_plot_media(val)
    elif isinstance(val, SixSequence) and all(isinstance(v, WBValue) for v in val):
        assert run
        # This check will break down if Image/Audio/... have child classes.
        if (
            len(val)
            and isinstance(val[0], BatchableMedia)
            and all(isinstance(v, type(val[0])) for v in val)
        ):

            if wandb.TYPE_CHECKING and TYPE_CHECKING:
                val = cast(Sequence["BatchableMedia"], val)

            items = _prune_max_seq(val)

            for i, item in enumerate(items):
                item.bind_to_run(run, key, namespace, id_=i)

            return items[0].seq_to_json(items, run, key, namespace)
        else:
            # TODO(adrian): Good idea to pass on the same key here? Maybe include
            # the array index?
            # There is a bug here: if this array contains two arrays of the same type of
            # anonymous media objects, their eventual names will collide.
            # This used to happen. The frontend doesn't handle heterogenous arrays
            # raise ValueError(
            #    "Mixed media types in the same list aren't supported")
            return [val_to_json(run, key, v, namespace=namespace) for v in val]

    if isinstance(val, WBValue):
        assert run
        if isinstance(val, Media) and not val.is_bound():
            if hasattr(val, "_log_type") and val._log_type in [
                "table",
                "partitioned-table",
                "joined-table",
            ]:
                # Special conditional to log tables as artifact entries as well.
                # I suspect we will generalize this as we transition to storing all
                # files in an artifact
                # we sanitize the key to meet the constraints defined in wandb_artifacts.py
                # in this case, leaving only alpha numerics or underscores.
                sanitized_key = re.sub(r"[^a-zA-Z0-9_]+", "", key)
                art = wandb.wandb_sdk.wandb_artifacts.Artifact(
                    "run-{}-{}".format(run.id, sanitized_key), "run_table"
                )
                art.add(val, key)
                run.log_artifact(art)

            # Partitioned tables and joined tables do not support being bound to runs.
            if not (
                hasattr(val, "_log_type")
                and val._log_type in ["partitioned-table", "joined-table"]
            ):
                val.bind_to_run(run, key, namespace)
        return val.to_json(run)

    return converted  # type: ignore


def _is_numpy_array(data):
    np = util.get_module(
        "numpy", required="Logging raw point cloud data requires numpy"
    )
    return isinstance(data, np.ndarray)


def _wb_filename(
    key, step, id, extension
):
    return "{}_{}_{}{}".format(str(key), str(step), str(id), extension)


def _numpy_arrays_to_lists(
    payload
):
    # Casts all numpy arrays to lists so we don't convert them to histograms, primarily for Plotly

    if isinstance(payload, dict):
        res = {}
        for key, val in six.iteritems(payload):
            res[key] = _numpy_arrays_to_lists(val)
        return res
    elif isinstance(payload, SixSequence) and not isinstance(payload, six.string_types):
        return [_numpy_arrays_to_lists(v) for v in payload]
    elif util.is_numpy_array(payload):
        if wandb.TYPE_CHECKING and TYPE_CHECKING:
            payload = cast("np.ndarray", payload)
        return [_numpy_arrays_to_lists(v) for v in payload.tolist()]
    # Protects against logging non serializable objects
    elif isinstance(payload, Media):
        return str(payload.__class__.__name__)
    return payload


def _prune_max_seq(seq):
    # If media type has a max respect it
    items = seq
    if hasattr(seq[0], "MAX_ITEMS") and seq[0].MAX_ITEMS < len(seq):  # type: ignore
        logging.warning(
            "Only %i %s will be uploaded."
            % (seq[0].MAX_ITEMS, seq[0].__class__.__name__)  # type: ignore
        )
        items = seq[: seq[0].MAX_ITEMS]  # type: ignore
    return items


def _data_frame_to_json(
    df, run, key, step
):
    """!NODOC Encode a Pandas DataFrame into the JSON/backend format.

    Writes the data to a file and returns a dictionary that we use to represent
    it in `Summary`'s.

    Arguments:
        df (pandas.DataFrame): The DataFrame. Must not have columns named
            "wandb_run_id" or "wandb_data_frame_id". They will be added to the
            DataFrame here.
        run (wandb_run.Run): The Run the DataFrame is associated with. We need
            this because the information we store on the DataFrame is derived
            from the Run it's in.
        key (str): Name of the DataFrame, ie. the summary key path in which it's
            stored. This is for convenience, so people exploring the
            directory tree can have some idea of what is in the Parquet files.
        step: History step or "summary".

    Returns:
        A dict representing the DataFrame that we can store in summaries or
        histories. This is the format:
        {
            '_type': 'data-frame',
                # Magic field that indicates that this object is a data frame as
                # opposed to a normal dictionary or anything else.
            'id': 'asdf',
                # ID for the data frame that is unique to this Run.
            'format': 'parquet',
                # The file format in which the data frame is stored. Currently can
                # only be Parquet.
            'project': 'wfeas',
                # (Current) name of the project that this Run is in. It'd be
                # better to store the project's ID because we know it'll never
                # change but we don't have that here. We store this just in
                # case because we use the project name in identifiers on the
                # back end.
            'path': 'media/data_frames/sdlk.parquet',
                # Path to the Parquet file in the Run directory.
        }
    """
    pandas = util.get_module("pandas")
    fastparquet = util.get_module("fastparquet")
    missing_reqs = []
    if not pandas:
        missing_reqs.append("pandas")
    if not fastparquet:
        missing_reqs.append("fastparquet")
    if len(missing_reqs) > 0:
        raise wandb.Error(
            "Failed to save data frame. Please run 'pip install %s'"
            % " ".join(missing_reqs)
        )

    data_frame_id = util.generate_id()

    df = df.copy()  # we don't want to modify the user's DataFrame instance.

    for _, series in df.items():
        for i, val in enumerate(series):
            if isinstance(val, WBValue):
                series.iat[i] = six.text_type(
                    json.dumps(val_to_json(run, key, val, namespace=step))
                )

    # We have to call this wandb_run_id because that name is treated specially by
    # our filtering code
    df["wandb_run_id"] = pandas.Series(
        [six.text_type(run.id)] * len(df.index), index=df.index
    )

    df["wandb_data_frame_id"] = pandas.Series(
        [six.text_type(data_frame_id)] * len(df.index), index=df.index
    )
    frames_dir = os.path.join(run.dir, _DATA_FRAMES_SUBDIR)
    util.mkdir_exists_ok(frames_dir)
    path = os.path.join(frames_dir, "{}-{}.parquet".format(key, data_frame_id))
    fastparquet.write(path, df)

    return {
        "id": data_frame_id,
        "_type": "data-frame",
        "format": "parquet",
        "project": run.project_name(),  # we don't have the project ID here
        "entity": run.entity,
        "run": run.id,
        "path": path,
    }


class _ClassesIdType(_dtypes.Type):
    name = "classesId"
    legacy_names = ["wandb.Classes_id"]
    types = [Classes]

    def __init__(
        self,
        classes_obj = None,
        valid_ids = None,
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

    def assign(self, py_obj = None):
        return self.assign_type(_dtypes.ConstType(py_obj))

    def assign_type(self, wb_type):
        valid_ids = self.params["valid_ids"].assign_type(wb_type)
        if not isinstance(valid_ids, _dtypes.InvalidType):
            return self

        return _dtypes.InvalidType()

    @classmethod
    def from_obj(cls, py_obj = None):
        return cls(py_obj)

    def to_json(self, artifact = None):
        cl_dict = super(_ClassesIdType, self).to_json(artifact)
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
        cls, json_dict, artifact = None,
    ):
        classes_obj = None
        if (
            json_dict.get("params", {}).get("classes_obj", {}).get("type")
            == "classes-file"
        ):
            if artifact is not None:
                classes_obj = artifact.get(
                    json_dict.get("params", {}).get("classes_obj", {}).get("path")
                )
            else:
                raise RuntimeError("Expected artifact to be non-null.")
        else:
            classes_obj = Classes.from_json(
                json_dict["params"]["classes_obj"], artifact
            )

        return cls(classes_obj)


class _VideoFileType(_dtypes.Type):
    name = "video-file"
    types = [Video]


class _HtmlFileType(_dtypes.Type):
    name = "html-file"
    types = [Html]


class _Object3DFileType(_dtypes.Type):
    name = "object3D-file"
    types = [Object3D]


_dtypes.TypeRegistry.add(_ClassesIdType)
_dtypes.TypeRegistry.add(_VideoFileType)
_dtypes.TypeRegistry.add(_HtmlFileType)
_dtypes.TypeRegistry.add(_Object3DFileType)

__all__ = [
    "Histogram",
    "Object3D",
    "Molecule",
    "Html",
    "Video",
    "ImageMask",
    "BoundingBoxes2D",
    "Classes",
    "Image",
    "Plotly",
    "history_dict_to_json",
    "val_to_json",
]
