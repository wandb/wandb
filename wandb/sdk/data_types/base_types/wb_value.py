from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Type, Union

from wandb import util

if TYPE_CHECKING:  # pragma: no cover
    from wandb.sdk.artifacts.artifact import Artifact

    from ...wandb_run import Run as LocalRun

    TypeMappingType = Dict[str, Type["WBValue"]]


def _server_accepts_client_ids() -> bool:
    from wandb.util import parse_version

    # First, if we are offline, assume the backend server cannot
    # accept client IDs. Unfortunately, this is the best we can do
    # until we are sure that all local versions are > "0.11.0" max_cli_version.
    # The practical implication is that tables logged in offline mode
    # will not show up in the workspace (but will still show up in artifacts). This
    # means we never lose data, and we can still view using weave. If we decided
    # to use client ids in offline mode, then the manifests and artifact data
    # would never be resolvable and would lead to failed uploads. Our position
    # is to never lose data - and instead take the tradeoff in the UI.
    if util._is_offline():
        return False

    # If the script is online, request the max_cli_version and ensure the server
    # is of a high enough version.
    max_cli_version = util._get_max_cli_version()
    if max_cli_version is None:
        return False
    accepts_client_ids: bool = parse_version("0.11.0") <= parse_version(max_cli_version)
    return accepts_client_ids


class _WBValueArtifactSource:
    artifact: "Artifact"
    name: Optional[str]

    def __init__(self, artifact: "Artifact", name: Optional[str] = None) -> None:
        self.artifact = artifact
        self.name = name


class _WBValueArtifactTarget:
    artifact: "Artifact"
    name: Optional[str]

    def __init__(self, artifact: "Artifact", name: Optional[str] = None) -> None:
        self.artifact = artifact
        self.name = name


class WBValue:
    """Typed objects that can be logged with `wandb.log()` and visualized by wandb.

    The objects will be serialized as JSON and always have a _type attribute that
    indicates how to interpret the other fields.
    """

    # Class Attributes
    _type_mapping: ClassVar[Optional["TypeMappingType"]] = None
    # override _log_type to indicate the type which the subclass deserializes
    _log_type: ClassVar[Optional[str]] = None

    # Instance Attributes
    _artifact_source: Optional[_WBValueArtifactSource]
    _artifact_target: Optional[_WBValueArtifactTarget]

    def __init__(self) -> None:
        self._artifact_source = None
        self._artifact_target = None

    def to_json(self, run_or_artifact: Union["LocalRun", "Artifact"]) -> dict:
        """Serialize the object into a JSON blob.

        Uses current run or artifact to store additional data.

        Args:
            run_or_artifact (wandb.Run | wandb.Artifact): the Run or Artifact for which
                this object should be generating JSON for - this is useful to to store
                additional data if needed.

        Returns:
            dict: JSON representation
        """
        raise NotImplementedError

    @classmethod
    def from_json(cls, json_obj: dict, source_artifact: "Artifact") -> "WBValue":
        """Deserialize a `json_obj` into it's class representation.

        If additional resources were stored in the `run_or_artifact` artifact during the
        `to_json` call, then those resources should be in the `source_artifact`.

        Args:
            json_obj (dict): A JSON dictionary to deserialize source_artifact
            (wandb.Artifact): An artifact which will hold any additional
                resources which were stored during the `to_json` function.
        """
        raise NotImplementedError

    @classmethod
    def with_suffix(cls: Type["WBValue"], name: str, filetype: str = "json") -> str:
        """Get the name with the appropriate suffix.

        Args:
            name (str): the name of the file
            filetype (str, optional): the filetype to use. Defaults to "json".

        Returns:
            str: a filename which is suffixed with it's `_log_type` followed by the
                filetype.
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
        json_obj: dict, source_artifact: "Artifact"
    ) -> Optional["WBValue"]:
        """Initialize a `WBValue` from a JSON blob based on the class that creatd it.

        Looks through all subclasses and tries to match the json obj with the class
        which created it. It will then call that subclass' `from_json` method.
        Importantly, this function will set the return object's `source_artifact`
        attribute to the passed in source artifact. This is critical for artifact
        bookkeeping. If you choose to create a wandb.Value via it's `from_json` method,
        make sure to properly set this `artifact_source` to avoid data duplication.

        Args:
            json_obj (dict): A JSON dictionary to deserialize. It must contain a `_type`
                key. This is used to lookup the correct subclass to use.
            source_artifact (wandb.Artifact): An artifact which will hold any additional
                resources which were stored during the `to_json` function.

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
    def type_mapping() -> "TypeMappingType":
        """Return a map from `_log_type` to subclass. Used to lookup correct types for deserialization.

        Returns:
            dict: dictionary of str:class
        """
        if WBValue._type_mapping is None:
            WBValue._type_mapping = {}
            frontier = [WBValue]
            explored = set()
            while len(frontier) > 0:
                class_option = frontier.pop()
                explored.add(class_option)
                if class_option._log_type is not None:
                    WBValue._type_mapping[class_option._log_type] = class_option
                for subclass in class_option.__subclasses__():
                    if subclass not in explored:
                        frontier.append(subclass)
        return WBValue._type_mapping

    def __eq__(self, other: object) -> bool:
        return id(self) == id(other)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def to_data_array(self) -> List[Any]:
        """Convert the object to a list of primitives representing the underlying data."""
        raise NotImplementedError

    def _set_artifact_source(
        self, artifact: "Artifact", name: Optional[str] = None
    ) -> None:
        assert (
            self._artifact_source is None
        ), "Cannot update artifact_source. Existing source: {}/{}".format(
            self._artifact_source.artifact, self._artifact_source.name
        )
        self._artifact_source = _WBValueArtifactSource(artifact, name)

    def _set_artifact_target(
        self, artifact: "Artifact", name: Optional[str] = None
    ) -> None:
        assert (
            self._artifact_target is None
        ), "Cannot update artifact_target. Existing target: {}/{}".format(
            self._artifact_target.artifact, self._artifact_target.name
        )
        self._artifact_target = _WBValueArtifactTarget(artifact, name)

    def _get_artifact_entry_ref_url(self) -> Optional[str]:
        # If the object is coming from another artifact
        if self._artifact_source and self._artifact_source.name:
            ref_entry = self._artifact_source.artifact.get_entry(
                type(self).with_suffix(self._artifact_source.name)
            )
            return str(ref_entry.ref_url())
        # Else, if the object is destined for another artifact and we support client IDs
        elif (
            self._artifact_target
            and self._artifact_target.name
            and self._artifact_target.artifact._client_id is not None
            and self._artifact_target.artifact._final
            and _server_accepts_client_ids()
        ):
            return "wandb-client-artifact://{}/{}".format(
                self._artifact_target.artifact._client_id,
                type(self).with_suffix(self._artifact_target.name),
            )
        # Else if we do not support client IDs, but online, then block on upload
        # Note: this is old behavior just to stay backwards compatible
        # with older server versions. This code path should be removed
        # once those versions are no longer supported. This path uses a .wait
        # which blocks the user process on artifact upload.
        elif (
            self._artifact_target
            and self._artifact_target.name
            and self._artifact_target.artifact._is_draft_save_started()
            and not util._is_offline()
            and not _server_accepts_client_ids()
        ):
            self._artifact_target.artifact.wait()
            ref_entry = self._artifact_target.artifact.get_entry(
                type(self).with_suffix(self._artifact_target.name)
            )
            return str(ref_entry.ref_url())
        return None

    def _get_artifact_entry_latest_ref_url(self) -> Optional[str]:
        if (
            self._artifact_target
            and self._artifact_target.name
            and self._artifact_target.artifact._client_id is not None
            and self._artifact_target.artifact._final
            and _server_accepts_client_ids()
        ):
            return "wandb-client-artifact://{}:latest/{}".format(
                self._artifact_target.artifact._sequence_client_id,
                type(self).with_suffix(self._artifact_target.name),
            )
        # Else if we do not support client IDs, then block on upload
        # Note: this is old behavior just to stay backwards compatible
        # with older server versions. This code path should be removed
        # once those versions are no longer supported. This path uses a .wait
        # which blocks the user process on artifact upload.
        elif (
            self._artifact_target
            and self._artifact_target.name
            and self._artifact_target.artifact._is_draft_save_started()
            and not util._is_offline()
            and not _server_accepts_client_ids()
        ):
            self._artifact_target.artifact.wait()
            ref_entry = self._artifact_target.artifact.get_entry(
                type(self).with_suffix(self._artifact_target.name)
            )
            return str(ref_entry.ref_url())
        return None
