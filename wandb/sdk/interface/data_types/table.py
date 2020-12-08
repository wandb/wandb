class Table(Media):
    """This is a table designed to display sets of records.

    Arguments:
        columns ([str]): Names of the columns in the table.
            Defaults to ["Input", "Output", "Expected"].
        data (array): 2D Array of values that will be displayed as strings.
        dataframe (pandas.DataFrame): DataFrame object used to create the table.
            When set, the other arguments are ignored.
    """

    MAX_ROWS = 10000
    MAX_ARTIFACT_ROWS = 50000
    artifact_type = "table"

    def __init__(
        self,
        columns=["Input", "Output", "Expected"],
        data=None,
        rows=None,
        dataframe=None,
    ):
        """rows is kept for legacy reasons, we use data to mimic the Pandas api
        """
        super(Table, self).__init__()
        self.columns = columns
        self.data = list(rows or data or [])
        if dataframe is not None:
            assert util.is_pandas_data_frame(
                dataframe
            ), "dataframe argument expects a `Dataframe` object"
            self.columns = list(dataframe.columns)
            self.data = []
            for row in range(len(dataframe)):
                self.add_data(
                    *tuple(dataframe[col].values[row] for col in self.columns)
                )

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        if len(self.data) != len(other.data) or self.columns != other.columns:
            return False

        for row_ndx in range(len(self.data)):
            for col_ndx in range(len(self.data[row_ndx])):
                if self.data[row_ndx][col_ndx] != other.data[row_ndx][col_ndx]:
                    return False

        return True

    def add_row(self, *row):
        logging.warning("add_row is deprecated, use add_data")
        self.add_data(*row)

    def add_data(self, *data):
        """Add a row of data to the table. Argument length should match column length"""
        if len(data) != len(self.columns):
            raise ValueError(
                "This table expects {} columns: {}".format(
                    len(self.columns), self.columns
                )
            )
        self.data.append(list(data))

    def _to_table_json(self, max_rows=None):
        # seperate method for testing
        if max_rows is None:
            max_rows = Table.MAX_ROWS
        if len(self.data) > max_rows:
            logging.warning("Truncating wandb.Table object to %i rows." % max_rows)
        return {"columns": self.columns, "data": self.data[:max_rows]}

    def bind_to_run(self, *args, **kwargs):
        data = self._to_table_json()
        tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ".table.json")
        data = numpy_arrays_to_lists(data)
        util.json_dump_safer(data, codecs.open(tmp_path, "w", encoding="utf-8"))
        self._set_file(tmp_path, is_tmp=True, extension=".table.json")
        super(Table, self).bind_to_run(*args, **kwargs)

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "table")

    @classmethod
    def from_json(cls, json_obj, source_artifact):
        data = []
        for row in json_obj["data"]:
            row_data = []
            for item in row:
                cell = item
                if isinstance(item, dict):
                    obj = WBValue.init_from_json(item, source_artifact)
                    if obj is not None:
                        cell = obj
                row_data.append(cell)
            data.append(row_data)

        return cls(json_obj["columns"], data=data,)

    def to_json(self, run_or_artifact):
        json_dict = super(Table, self).to_json(run_or_artifact)
        wandb_run, wandb_artifacts = _safe_sdk_import()

        if isinstance(run_or_artifact, wandb_run.Run):
            json_dict.update(
                {
                    "_type": "table-file",
                    "ncols": len(self.columns),
                    "nrows": len(self.data),
                }
            )

        elif isinstance(run_or_artifact, wandb_artifacts.Artifact):
            for column in self.columns:
                if "." in column:
                    raise ValueError(
                        "invalid column name: {} - tables added to artifacts must not contain periods.".format(
                            column
                        )
                    )
            artifact = run_or_artifact
            mapped_data = []
            data = self._to_table_json(Table.MAX_ARTIFACT_ROWS)["data"]
            for row in data:
                mapped_row = []
                for v in row:
                    if isinstance(v, WBValue):
                        mapped_row.append(v.to_json(artifact))
                    else:
                        mapped_row.append(v)
                mapped_data.append(mapped_row)
            json_dict.update(
                {
                    "_type": Table.artifact_type,
                    "columns": self.columns,
                    "data": mapped_data,
                    "ncols": len(self.columns),
                    "nrows": len(mapped_data),
                }
            )
        else:
            raise ValueError("to_json accepts wandb_run.Run or wandb_artifact.Artifact")

        return json_dict
