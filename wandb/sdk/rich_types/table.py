import pathlib
from typing import TYPE_CHECKING, Optional, Sequence, Union

from wandb import util

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

    _num_columns: int
    _num_rows: int

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

    def bind_to_run(
        self, interface, root_dir: pathlib.Path, *prefix, name: Optional[str] = None
    ) -> None:
        """Bind this table object to a run.

        Args:
            interface: The interface to bind to.
            start: The path to the run directory.
            prefix: A path prefix to prepend to the media path.
            name: The name of the media file.
        """
        pass


class PartitionedTable(Media):
    ...


class JoinedTable(Media):
    ...
