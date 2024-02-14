import json
from typing import Any, Dict, ItemsView, NewType, Optional, Sequence

from wandb.proto import wandb_internal_pb2
from wandb.sdk.lib import proto_util, telemetry

BackendConfigDict = NewType("BackendConfigDict", Dict[str, Any])
"""Run config dictionary in the format used by the backend."""


class ConfigState:
    """The configuration of a run."""

    def __init__(self):
        self._tree: Dict[str, Any] = {}
        """A tree with string-valued nodes and JSON leaves.

        Leaves are Python objects that are valid JSON values:

        * Primitives like strings and numbers
        * Dictionaries from strings to JSON objects
        * Lists of JSON objects
        """

    def items(self) -> ItemsView[str, Any]:
        """Returns the items of the underlying dictionary representation.

        Note, this is not the same dictionary as returned by `to_backend_dict`.
        """
        return self._tree.items()

    def update_from_proto(
        self,
        config_record: wandb_internal_pb2.ConfigRecord,
    ) -> None:
        """Applies update and remove commands."""
        for config_item in config_record.update:
            self._update_at_path(
                _key_path(config_item),
                json.loads(config_item.value_json),
            )

        for config_item in config_record.remove:
            self._delete_at_path(_key_path(config_item))

    def add_unset_keys(self, other_config_tree: Dict[str, Any]) -> None:
        """Uses the given dict for any keys that aren't already set."""
        for k, v in other_config_tree:
            if k not in self._tree:
                self._tree[k] = v

    def to_backend_dict(
        self,
        telemetry_record: telemetry.TelemetryRecord,
        framework: Optional[str],
        start_time_millis: int,
        metric_pbdicts: Sequence[Dict[int, Any]],
    ) -> BackendConfigDict:
        """Returns a dictionary representation expected by the backend.

        The backend expects the configuration in a specific format, and the
        config is also used to store additional metadata about the run.

        Args:
            telemetry_record: Telemetry information to insert.
            framework: The detected framework used in the run (e.g. TensorFlow).
            start_time_millis: The run's start time in Unix milliseconds.
            metric_pbdicts: List of dict representations of metric protobuffers.
        """
        backend_dict = self._tree.copy()
        wandb_internal = backend_dict.setdefault("_wandb", {})

        ###################################################
        # Telemetry information
        ###################################################
        if py_version := telemetry_record.python_version:
            wandb_internal["python_version"] = py_version

        if cli_version := telemetry_record.cli_version:
            wandb_internal["cli_version"] = cli_version

        if framework:
            wandb_internal["framework"] = framework

        if huggingface_version := telemetry_record.huggingface_version:
            wandb_internal["huggingface_version"] = huggingface_version

        wandb_internal["is_jupyter_run"] = telemetry_record.env.jupyter
        wandb_internal["is_kaggle_kernel"] = telemetry_record.env.kaggle

        # TODO: ?
        wandb_internal["start_time"] = start_time_millis

        # The full telemetry record. Admittedly this is redundant with some of
        # the above, but we do it because.. uh...
        wandb_internal["t"] = proto_util.proto_encode_to_dict(telemetry_record)

        ###################################################
        # Metrics
        ###################################################
        if metric_pbdicts:
            wandb_internal["m"] = metric_pbdicts

        return BackendConfigDict(
            {
                key: {
                    # Configurations can be stored in a hand-written YAML file,
                    # and users can add descriptions to their hyperparameters
                    # there. However, we don't support a way to set descriptions
                    # via code, so this is always None.
                    "desc": None,
                    "value": value,
                }
                for key, value in self._tree
            }
        )

    def _update_at_path(
        self,
        key_path: Sequence[str],
        value: Any,
    ) -> None:
        """Sets the value at the path in the config tree."""
        update_in = self._tree
        for key in key_path[:-1]:
            update_in = update_in.setdefault(key, {})
        update_in[key_path[-1]] = value

    def _delete_at_path(
        self,
        key_path: Sequence[str],
    ) -> None:
        """Removes the subtree at the path in the config tree."""
        remove_from = self._tree

        for key in key_path[:-1]:
            if key not in remove_from:
                return
            remove_from = remove_from[key]

        del remove_from[key_path[-1]]


def _key_path(config_item: wandb_internal_pb2.ConfigItem) -> Sequence[str]:
    """Returns the key path referenced by the config item."""
    if config_item.nested_key:
        return config_item.nested_key
    elif config_item.key:
        return [config_item.key]
    else:
        raise AssertionError(
            "Invalid ConfigItem: either key or nested_key must be set",
        )
