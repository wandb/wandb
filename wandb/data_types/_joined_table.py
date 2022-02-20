import base64
import binascii
import os

from _media import Media
from _partitioned_table import PartitionedTable
from _table import Table

from wandb.sdk.interface import _dtypes
from wandb_run import Run


class JoinedTable(Media):
    """Joins two tables for visualization in the Artifact UI

    Arguments:
        table1 (str, wandb.Table, ArtifactEntry):
            the path to a wandb.Table in an artifact, the table object, or ArtifactEntry
        table2 (str, wandb.Table):
            the path to a wandb.Table in an artifact, the table object, or ArtifactEntry
        join_key (str, [str, str]):
            key or keys to perform the join
    """

    _log_type = "joined-table"

    def __init__(self, table1, table2, join_key):
        super(JoinedTable, self).__init__()

        if not isinstance(join_key, str) and (
            not isinstance(join_key, list) or len(join_key) != 2
        ):
            raise ValueError(
                "JoinedTable join_key should be a string or a list of two strings"
            )

        if not self._validate_table_input(table1):
            raise ValueError(
                "JoinedTable table1 should be an artifact path to a table or wandb.Table object"
            )

        if not self._validate_table_input(table2):
            raise ValueError(
                "JoinedTable table2 should be an artifact path to a table or wandb.Table object"
            )

        self._table1 = table1
        self._table2 = table2
        self._join_key = join_key

    @classmethod
    def from_json(cls, json_obj, source_artifact):
        t1 = source_artifact.get(json_obj["table1"])
        if t1 is None:
            t1 = json_obj["table1"]

        t2 = source_artifact.get(json_obj["table2"])
        if t2 is None:
            t2 = json_obj["table2"]

        return cls(
            t1,
            t2,
            json_obj["join_key"],
        )

    @staticmethod
    def _validate_table_input(table):
        """Helper method to validate that the table input is one of the 3 supported types"""
        return (
            (type(table) == str and table.endswith(".table.json"))
            or isinstance(table, Table)
            or isinstance(table, PartitionedTable)
            or (hasattr(table, "ref_url") and table.ref_url().endswith(".table.json"))
        )

    def _ensure_table_in_artifact(self, table, artifact, table_ndx):
        """Helper method to add the table to the incoming artifact. Returns the path"""
        if isinstance(table, Table) or isinstance(table, PartitionedTable):
            table_name = "t{}_{}".format(table_ndx, str(id(self)))
            if (
                table._artifact_source is not None
                and table._artifact_source.name is not None
            ):
                table_name = os.path.basename(table._artifact_source.name)
            entry = artifact.add(table, table_name)
            table = entry.path
        # Check if this is an ArtifactEntry
        elif hasattr(table, "ref_url"):
            # Give the new object a unique, yet deterministic name
            name = binascii.hexlify(
                base64.standard_b64decode(table.entry.digest)
            ).decode("ascii")[:20]
            entry = artifact.add_reference(
                table.ref_url(), "{}.{}.json".format(name, table.name.split(".")[-2])
            )[0]
            table = entry.path

        err_str = "JoinedTable table:{} not found in artifact. Add a table to the artifact using Artifact#add(<table>, {}) before adding this JoinedTable"
        if table not in artifact._manifest.entries:
            raise ValueError(err_str.format(table, table))

        return table

    def to_json(self, artifact_or_run):
        json_obj = {
            "_type": JoinedTable._log_type,
        }
        if isinstance(artifact_or_run, Run):
            artifact_entry_url = self._get_artifact_entry_ref_url()
            if artifact_entry_url is None:
                raise ValueError(
                    "JoinedTables must first be added to an Artifact before logging to a Run"
                )
            json_obj["artifact_path"] = artifact_entry_url
        else:
            table1 = self._ensure_table_in_artifact(self._table1, artifact_or_run, 1)
            table2 = self._ensure_table_in_artifact(self._table2, artifact_or_run, 2)
            json_obj.update(
                {
                    "table1": table1,
                    "table2": table2,
                    "join_key": self._join_key,
                }
            )
        return json_obj

    def __ne__(self, other):
        return not self.__eq__(other)

    def _eq_debug(self, other, should_assert=False):
        eq = isinstance(other, JoinedTable)
        assert not should_assert or eq, "Found type {}, expected {}".format(
            other.__class__, JoinedTable
        )
        eq = eq and self._join_key == other._join_key
        assert not should_assert or eq, "Found {} join key, expected {}".format(
            other._join_key, self._join_key
        )
        eq = eq and self._table1._eq_debug(other._table1, should_assert)
        eq = eq and self._table2._eq_debug(other._table2, should_assert)
        return eq

    def __eq__(self, other):
        return self._eq_debug(other, False)

    def bind_to_run(self, *args, **kwargs):
        raise ValueError("JoinedTables cannot be bound to runs")


class _JoinedTableType(_dtypes.Type):
    name = "joined-table"
    types = [JoinedTable]


_dtypes.TypeRegistry.add(_JoinedTableType)
