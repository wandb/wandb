import wandb
from wandb import util


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
    )

    if TYPE_CHECKING:
        from .wandb_artifacts import Artifact as LocalArtifact
        from .wandb_run import Run as LocalRun
        from wandb.apis.public import Artifact as PublicArtifact
        from numpy import np  # type: ignore

        TypeMappingType = Dict[str, Type["WBValue"]]
        NumpyHistogram = Tuple[np.ndarray, np.ndarray]


class _WBValueArtifactSource(object):
    artifact: "PublicArtifact"
    name: Optional[str]

    def __init__(self, artifact: "PublicArtifact", name: str = None) -> None:
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
    _type_mapping: ClassVar[Optional["TypeMappingType"]] = None
    # override artifact_type to indicate the type which the subclass deserializes
    artifact_type: ClassVar[Optional[str]] = None

    # Instance Attributes
    artifact_source: Optional[_WBValueArtifactSource]

    def __init__(self) -> None:
        self.artifact_source = None

    def to_json(self, run_or_artifact: Union["LocalRun", "LocalArtifact"]) -> dict:
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
        cls: Type["WBValue"], json_obj: dict, source_artifact: "PublicArtifact"
    ) -> "WBValue":
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
    def with_suffix(cls: Type["WBValue"], name: str, filetype: str = "json") -> str:
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
        json_obj: dict, source_artifact: "PublicArtifact"
    ) -> "Optional[WBValue]":
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
    def type_mapping() -> "TypeMappingType":
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

    def __eq__(self, other: object) -> bool:
        return id(self) == id(other)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def set_artifact_source(self, artifact: "PublicArtifact", name: str = None) -> None:
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

    MAX_LENGTH: int = 512

    def __init__(
        self,
        sequence: Optional[Sequence] = None,
        np_histogram: Optional["NumpyHistogram"] = None,
        num_bins: int = 64,
    ) -> None:

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

    def to_json(self, run: Union["LocalRun", "LocalArtifact"] = None) -> dict:
        return {"_type": "histogram", "values": self.histogram, "bins": self.bins}


__all__ = ["WBValue", "Histogram"]
