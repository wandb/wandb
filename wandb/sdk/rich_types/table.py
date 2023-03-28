import pathlib
from typing import TYPE_CHECKING, Any, Optional, Sequence, Union

from wandb import util
from wandb.sdk.data_types import _dtypes

from .media import Media

if TYPE_CHECKING:
    import pandas as pd  # type: ignore


class Table(Media):
    RELATIVE_PATH = pathlib.Path("media") / "table"
    DEFAULT_FORMAT = "TABLE.JSON"
    OBJ_TYPE = "table-file"

    _source_path: pathlib.Path
    _is_temp_path: bool
    _bind_path: Optional[pathlib.Path]

    def __init__(
        self,
        data: Optional[Union[Sequence, "pd.DataFrame"]] = None,
        columns: Optional[Sequence[str]] = None,
    ) -> None:
        self._data = []
        self._columns = []

        if data is None:
            self._from_list([], columns)
        elif util.is_numpy_array(data):
            self._from_numpy(data, columns)
        elif util.is_pandas_data_frame(data):
            self._from_pandas(data)
        elif isinstance(data, list):
            self._from_list(data, columns)
        else:
            raise ValueError(f"Unsupported data type: {type(data)}")

    def _from_numpy(self, data, columns):
        data = data.tolist()
        return self._from_list(data, columns)

    def _from_pandas(self, data):
        columns = data.columns.tolist()
        data = data.values.tolist()
        return self._from_list(data, columns)

    def _from_list(self, data, columns):
        if columns is None:
            columns = ["Input", "Output", "Expected"]

        assert isinstance(columns, list), "columns must be a list"
        assert all(
            isinstance(c, (str, int)) for c in columns
        ), "columns must be a list of strings or ints"

        self._columns = columns

        for row in data:
            self.add_data(row)

    def add_data(self, data):
        assert len(data) == len(
            self._columns
        ), "data must have the same number of columns as the columns argument"

        self._data.append(data)

    def _save_table_to_file(self) -> None:
        self._format = self.DEFAULT_FORMAT.lower()
        self._source_path = self._generate_temp_path(f".{self._format}")
        self._is_temp_path = True
        data = {"columns": self._columns, "data": self._data}
        import json

        with open(self._source_path, "w") as f:
            json.dump(data, f)

        self._sha256 = self._compute_sha256(self._source_path)
        self._size = self._source_path.stat().st_size

    def bind_to_run(
        self, interface, root_dir: pathlib.Path, *namespace, name: Optional[str] = None
    ) -> None:
        """Bind this table object to a run.

        Args:
            interface: The interface to bind to.
            start: The path to the run directory.
            prefix: A path prefix to prepend to the media path.
            name: The name of the media file.
        """
        self._save_table_to_file()  # TODO: why do we save to temp file and move seems wasteful
        super().bind_to_run(
            interface,
            root_dir,
            *namespace,
            name or self._sha256[:20],
            suffix=f".{self._format}",
        )

    def to_json(self) -> dict:
        serialized = super().to_json()
        serialized["ncols"] = len(self._columns)
        serialized["nrows"] = len(self._data)
        return serialized


class PartitionedTable(Media):
    ...


class JoinedTable(Media):
    ...
