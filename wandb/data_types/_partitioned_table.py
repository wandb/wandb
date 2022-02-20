import wandb
from wandb.sdk.interface import _dtypes

from ._media import Media


class _PartitionTablePartEntry:
    """Helper class for PartitionTable to track its parts"""

    def __init__(self, entry, source_artifact):
        self.entry = entry
        self.source_artifact = source_artifact
        self._part = None

    def get_part(self):
        if self._part is None:
            self._part = self.source_artifact.get(self.entry.path)
        return self._part

    def free(self):
        self._part = None


class PartitionedTable(Media):
    """PartitionedTable represents a table which is composed
    by the union of multiple sub-tables. Currently, PartitionedTable
    is designed to point to a directory within an artifact.
    """

    _log_type = "partitioned-table"

    def __init__(self, parts_path):
        """
        Args:
            parts_path (str): path to a directory of tables in the artifact
        """
        super(PartitionedTable, self).__init__()
        self.parts_path = parts_path
        self._loaded_part_entries = {}

    def to_json(self, artifact_or_run):
        json_obj = {
            "_type": PartitionedTable._log_type,
        }
        if isinstance(artifact_or_run, wandb.sdk.wandb_run.Run):
            artifact_entry_url = self._get_artifact_entry_ref_url()
            if artifact_entry_url is None:
                raise ValueError(
                    "PartitionedTables must first be added to an Artifact before logging to a Run"
                )
            json_obj["artifact_path"] = artifact_entry_url
        else:
            json_obj["parts_path"] = self.parts_path
        return json_obj

    @classmethod
    def from_json(cls, json_obj, source_artifact):
        instance = cls(json_obj["parts_path"])
        entries = source_artifact.manifest.get_entries_in_directory(
            json_obj["parts_path"]
        )
        for entry in entries:
            instance._add_part_entry(entry, source_artifact)
        return instance

    def iterrows(self):
        """Iterate over rows as (ndx, row)
        Yields
        ------
        index : int
            The index of the row.
        row : List[any]
            The data of the row
        """
        columns = None
        ndx = 0
        for entry_path in self._loaded_part_entries:
            part = self._loaded_part_entries[entry_path].get_part()
            if columns is None:
                columns = part.columns
            elif columns != part.columns:
                raise ValueError(
                    "Table parts have non-matching columns. {} != {}".format(
                        columns, part.columns
                    )
                )
            for _, row in part.iterrows():
                yield ndx, row
                ndx += 1

            self._loaded_part_entries[entry_path].free()

    def _add_part_entry(self, entry, source_artifact):
        self._loaded_part_entries[entry.path] = _PartitionTablePartEntry(
            entry, source_artifact
        )

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.parts_path == other.parts_path

    def bind_to_run(self, *args, **kwargs):
        raise ValueError("PartitionedTables cannot be bound to runs")


class _PartitionedTableType(_dtypes.Type):
    name = "partitioned-table"
    types = [PartitionedTable]


_dtypes.TypeRegistry.add(_PartitionedTableType)
