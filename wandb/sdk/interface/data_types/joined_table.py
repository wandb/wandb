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

    artifact_type = "joined-table"

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

        return cls(t1, t2, json_obj["join_key"],)

    @staticmethod
    def _validate_table_input(table):
        """Helper method to validate that the table input is one of the 3 supported types"""
        return (
            (type(table) == str and table.endswith(".table.json"))
            or isinstance(table, Table)
            or (hasattr(table, "ref_url") and table.ref_url().endswith(".table.json"))
        )

    def _ensure_table_in_artifact(self, table, artifact, table_ndx):
        """Helper method to add the table to the incoming artifact. Returns the path"""
        if isinstance(table, Table):
            table_name = "t{}_{}".format(table_ndx, str(id(self)))
            if (
                table.artifact_source is not None
                and table.artifact_source["name"] is not None
            ):
                table_name = os.path.basename(table.artifact_source["name"])
            entry = artifact.add(table, table_name)
            table = entry.path
        # Check if this is an ArtifactEntry
        elif hasattr(table, "ref_url"):
            # Give the new object a unique, yet deterministic name
            name = binascii.hexlify(
                base64.standard_b64decode(table.entry.digest)
            ).decode("ascii")[:8]
            entry = artifact.add_reference(
                table.ref_url(), "{}.table.json".format(name)
            )[0]
            table = entry.path

        err_str = "JoinedTable table:{} not found in artifact. Add a table to the artifact using Artifact#add(<table>, {}) before adding this JoinedTable"
        if table not in artifact._manifest.entries:
            raise ValueError(err_str.format(table, table))

        return table

    def to_json(self, artifact):
        json_obj = super(JoinedTable, self).to_json(artifact)

        table1 = self._ensure_table_in_artifact(self._table1, artifact, 1)
        table2 = self._ensure_table_in_artifact(self._table2, artifact, 2)

        json_obj.update(
            {
                "_type": JoinedTable.artifact_type,
                "table1": table1,
                "table2": table2,
                "join_key": self._join_key,
            }
        )
        return json_obj

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        return (
            self._table1 == other._table1
            and self._table2 == other._table2
            and self._join_key == other._join_key
        )
