import codecs
import hashlib
import json
import os
import shutil

import six
import wandb
from wandb import util
from wandb._globals import _datatypes_callback
from wandb.compat import tempfile

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
    )

    if TYPE_CHECKING:
        from .wandb_artifacts import Artifact as LocalArtifact
        from .wandb_run import Run as LocalRun
        from wandb.apis.public import Artifact as PublicArtifact
        from numpy import np  # type: ignore
        from typing import TextIO

        TypeMappingType = Dict[str, Type["WBValue"]]
        NumpyHistogram = Tuple[np.ndarray, np.ndarray]

MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")


def wb_filename(key, step, id, extension):
    return "{}_{}_{}{}".format(key, str(step), id, extension)


def _safe_sdk_import():
    """Safely import due to circular deps"""

    from .wandb_artifacts import Artifact as LocalArtifact
    from .wandb_run import Run as LocalRun

    return LocalRun, LocalArtifact


def is_numpy_array(data):
    np = util.get_module(
        "numpy", required="Logging raw point cloud data requires numpy"
    )
    return isinstance(data, np.ndarray)


class _WBValueArtifactSource(object):
    # artifact: "PublicArtifact"
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
    # override artifact_type to indicate the type which the subclass deserializes
    artifact_type = None

    # Instance Attributes
    # artifact_source: Optional[_WBValueArtifactSource]

    def __init__(self):
        self.artifact_source = None

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
            str: a filename which is suffixed with it's `artifact_type` followed by the filetype
        """
        if cls.artifact_type is not None:
            suffix = cls.artifact_type + "." + filetype
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
            obj.set_artifact_source(source_artifact)
            return obj

        return None

    @staticmethod
    def type_mapping():
        """Returns a map from `artifact_type` to subclass. Used to lookup correct types for deserialization.

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
                if class_option.artifact_type is not None:
                    WBValue._type_mapping[class_option.artifact_type] = class_option
                for subclass in class_option.__subclasses__():
                    if subclass not in explored:
                        frontier.append(subclass)
        return WBValue._type_mapping

    def __eq__(self, other):
        return id(self) == id(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def set_artifact_source(self, artifact, name = None):
        self.artifact_source = _WBValueArtifactSource(artifact, name)


class Histogram(WBValue):
    """wandb class for histograms.

    This object works just like numpy's histogram function
    https://docs.scipy.org/doc/numpy/reference/generated/numpy.histogram.html

    Examples:
        Generate histogram from a sequence
        ```
        wandb.Histogram([1,2,3])
        ```

        Efficiently initialize from np.histogram.
        ```
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
        return {"_type": "histogram", "values": self.histogram, "bins": self.bins}


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
        self, run, key, step, id_ = None
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
        assert isinstance(self._path, str)
        assert isinstance(self._sha256, str)

        if run is None:
            raise TypeError('Argument "run" must not be None.')
        self._run = run

        # Following assertion required for mypy
        assert self._run is not None

        base_path = os.path.join(self._run.dir, self.get_media_subdir())

        if self._extension is None:
            _, extension = os.path.splitext(os.path.basename(self._path))
        else:
            extension = self._extension

        if id_ is None:
            id_ = self._sha256[:8]

        file_path = wb_filename(key, step, id_, extension)
        media_path = os.path.join(self.get_media_subdir(), file_path)
        new_path = os.path.join(base_path, file_path)
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
        json_obj = {}
        run_class, artifact_class = _safe_sdk_import()
        if isinstance(run, run_class):
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
            assert isinstance(self._path, str)

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
        elif isinstance(run, artifact_class):
            if self.file_is_set():
                # The following two assertions are guaranteed to pass
                # by definition of the call above, but are needed for
                # mypy to understand that these are strings below.
                assert isinstance(self._path, str)
                assert isinstance(self._sha256, str)
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
                            self._sha256[:8],
                            os.path.basename(self._path),
                        )

                    # if not, check to see if there is a source artifact for this object
                    if (
                        self.artifact_source
                        is not None
                        # and self.artifact_source.artifact != artifact
                    ):
                        default_root = self.artifact_source.artifact._default_root()
                        # if there is, get the name of the entry (this might make sense to move to a helper off artifact)
                        if self._path.startswith(default_root):
                            name = self._path[len(default_root) :]
                            name = name.lstrip(os.sep)

                        # Add this image as a reference
                        path = self.artifact_source.artifact.get_path(name)
                        artifact.add_reference(path.ref_url(), name=name)
                    else:
                        entry = artifact.add_file(
                            self._path, name=name, is_tmp=self._is_tmp
                        )
                        name = entry.path

                json_obj["path"] = name
            json_obj["_type"] = self.artifact_type
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
    ```
    [[x y z],       ...] nx3
    [x y z c],     ...] nx4 where c is a category with supported range [1, 14]
    [x y z r g b], ...] nx4 where is rgb is color
    ```
    """

    SUPPORTED_TYPES = set(
        ["obj", "gltf", "babylon", "stl", "pts.json"]
    )
    artifact_type = "object3D-file"

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
                MEDIA_TMP.name, util.generate_id() + "." + extension
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

            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ".pts.json")
            json.dump(
                data,
                codecs.open(tmp_path, "w", encoding="utf-8"),
                separators=(",", ":"),
                sort_keys=True,
                indent=4,
            )
            self._set_file(tmp_path, is_tmp=True, extension=".pts.json")
        elif is_numpy_array(data_or_path):
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
            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ".pts.json")
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
        json_dict["_type"] = Object3D.artifact_type

        _, artifact_class = _safe_sdk_import()

        if isinstance(run_or_artifact, artifact_class):
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
                MEDIA_TMP.name, util.generate_id() + "." + extension
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
        json_dict["_type"] = "molecule-file"
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

    artifact_type = "html-file"

    def __init__(self, data, inject = True):
        super(Html, self).__init__()
        data_is_path = isinstance(data, str) and os.path.exists(data)
        data_path = ""
        if data_is_path:
            assert isinstance(data, str)
            data_path = data
            with open(data_path, "r") as file:
                self.html = file.read()
        elif isinstance(data, str):
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
            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ".html")
            with open(tmp_path, "w") as out:
                print(self.html, file=out)

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
        json_dict["_type"] = "html-file"
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


__all__ = [
    "WBValue",
    "Histogram",
    "Media",
    "BatchableMedia",
    "Object3D",
    "Molecule",
    "Html",
]
