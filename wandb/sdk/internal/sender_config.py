import json
from typing import Any, Dict, NewType, Optional, Sequence

from wandb.proto import wandb_internal_pb2
from wandb.sdk.lib import proto_util, telemetry

BackendConfigDict = NewType("BackendConfigDict", Dict[str, Any])
"""Run config dictionary in the format used by the backend."""

_WANDB_INTERNAL_KEY = "_wandb"


class ConfigState:
    """The configuration of a run."""

    def __init__(self, tree: Optional[Dict[str, Any]] = None) -> None:
        self._tree: Dict[str, Any] = tree or {}
        """A tree with string-valued nodes and JSON leaves.

        Leaves are Python objects that are valid JSON values:

        * Primitives like strings and numbers
        * Dictionaries from strings to JSON objects
        * Lists of JSON objects
        """

    def non_internal_config(self) -> Dict[str, Any]:
        """Returns the config settings minus "_wandb"."""
        return {k: v for k, v in self._tree.items() if k != _WANDB_INTERNAL_KEY}

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

    def merge_resumed_config(self, old_config_tree: Dict[str, Any]) -> None:
        """Merges the config from a run that's being resumed."""
        # Add any top-level keys that aren't already set.
        self._add_unset_keys_from_subtree(old_config_tree, [])

        # Unfortunately, when a user logs visualizations, we store them in the
        # run's config. When resuming a run, we want to avoid erasing previously
        # logged visualizations, hence this special handling:
        self._add_unset_keys_from_subtree(
            old_config_tree,
            [_WANDB_INTERNAL_KEY, "visualize"],
        )
        self._add_unset_keys_from_subtree(
            old_config_tree,
            [_WANDB_INTERNAL_KEY, "viz"],
        )

    def _add_unset_keys_from_subtree(
        self,
        old_config_tree: Dict[str, Any],
        path: Sequence[str],
    ) -> None:
        """Uses the given subtree for keys that aren't already set."""
        old_subtree = _subtree(old_config_tree, path, create=False)
        if not old_subtree:
            return

        new_subtree = _subtree(self._tree, path, create=True)
        assert new_subtree is not None

        for key, value in old_subtree.items():
            if key not in new_subtree:
                new_subtree[key] = value

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
        wandb_internal = backend_dict.setdefault(_WANDB_INTERNAL_KEY, {})

        ###################################################
        # Telemetry information
        ###################################################
        py_version = telemetry_record.python_version
        if py_version:
            wandb_internal["python_version"] = py_version

        cli_version = telemetry_record.cli_version
        if cli_version:
            wandb_internal["cli_version"] = cli_version

        if framework:
            wandb_internal["framework"] = framework

        huggingface_version = telemetry_record.huggingface_version
        if huggingface_version:
            wandb_internal["huggingface_version"] = huggingface_version

        wandb_internal["is_jupyter_run"] = telemetry_record.env.jupyter
        wandb_internal["is_kaggle_kernel"] = telemetry_record.env.kaggle
        wandb_internal["start_time"] = start_time_millis

        # The full telemetry record.
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
                for key, value in self._tree.items()
            }
        )

    def _update_at_path(
        self,
        key_path: Sequence[str],
        value: Any,
    ) -> None:
        """Sets the value at the path in the config tree."""
        subtree = _subtree(self._tree, key_path[:-1], create=True)
        assert subtree is not None

        subtree[key_path[-1]] = value

    def _delete_at_path(
        self,
        key_path: Sequence[str],
    ) -> None:
        """Removes the subtree at the path in the config tree."""
        subtree = _subtree(self._tree, key_path[:-1], create=False)
        if subtree:
            del subtree[key_path[-1]]


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


def _subtree(
    tree: Dict[str, Any],
    key_path: Sequence[str],
    *,
    create: bool = False,
) -> Optional[Dict[str, Any]]:
    """Returns a subtree at the given path."""
    for key in key_path:
        subtree = tree.get(key)

        if not subtree:
            if create:
                subtree = {}
                tree[key] = subtree
            else:
                return None

        tree = subtree

    return tree
