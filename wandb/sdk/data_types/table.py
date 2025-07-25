import base64
import binascii
import codecs
import datetime
import json
import logging
import os
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Set, Tuple

import wandb
from wandb import util
from wandb.sdk.lib import runid

from . import _dtypes
from ._private import MEDIA_TMP
from .base_types.media import Media, _numpy_arrays_to_lists
from .base_types.wb_value import WBValue
from .table_decorators import (
    allow_incremental_logging_after_append,
    allow_relogging_after_mutation,
    ensure_not_incremental,
)
from .utils import _json_helper

if TYPE_CHECKING:
    from wandb.sdk.artifacts import artifact

    from ...wandb_run import Run as LocalRun


class _TableLinkMixin:
    def set_table(self, table):
        self._table = table


class _TableKey(str, _TableLinkMixin):
    def set_table(self, table, col_name):
        assert col_name in table.columns
        self._table = table
        self._col_name = col_name


class _TableIndex(int, _TableLinkMixin):
    def get_row(self):
        row = {}
        if self._table:
            row = {
                c: self._table.data[self][i] for i, c in enumerate(self._table.columns)
            }

        return row


class _PrimaryKeyType(_dtypes.Type):
    name = "primaryKey"
    legacy_names = ["wandb.TablePrimaryKey"]

    def assign_type(self, wb_type=None):
        if isinstance(wb_type, _dtypes.StringType) or isinstance(
            wb_type, _PrimaryKeyType
        ):
            return self
        return _dtypes.InvalidType()

    @classmethod
    def from_obj(cls, py_obj):
        if not isinstance(py_obj, _TableKey):
            raise TypeError("py_obj must be a wandb.Table")
        else:
            return cls()


class _ForeignKeyType(_dtypes.Type):
    name = "foreignKey"
    legacy_names = ["wandb.TableForeignKey"]
    types = [_TableKey]

    def __init__(self, table, col_name):
        assert isinstance(table, Table)
        assert isinstance(col_name, str)
        assert col_name in table.columns
        self.params.update({"table": table, "col_name": col_name})

    def assign_type(self, wb_type=None):
        if isinstance(wb_type, _dtypes.StringType):
            return self
        elif (
            isinstance(wb_type, _ForeignKeyType)
            and id(self.params["table"]) == id(wb_type.params["table"])
            and self.params["col_name"] == wb_type.params["col_name"]
        ):
            return self

        return _dtypes.InvalidType()

    @classmethod
    def from_obj(cls, py_obj):
        if not isinstance(py_obj, _TableKey):
            raise TypeError("py_obj must be a _TableKey")
        else:
            return cls(py_obj._table, py_obj._col_name)

    def to_json(self, artifact=None):
        res = super().to_json(artifact)
        if artifact is not None:
            table_name = f"media/tables/t_{runid.generate_id()}"
            entry = artifact.add(self.params["table"], table_name)
            res["params"]["table"] = entry.path
        else:
            raise AssertionError(
                "_ForeignKeyType does not support serialization without an artifact"
            )
        return res

    @classmethod
    def from_json(
        cls,
        json_dict,
        artifact,
    ):
        table = None
        col_name = None
        if artifact is None:
            raise AssertionError(
                "_ForeignKeyType does not support deserialization without an artifact"
            )
        else:
            table = artifact.get(json_dict["params"]["table"])
            col_name = json_dict["params"]["col_name"]

        if table is None:
            raise AssertionError("Unable to deserialize referenced table")

        return cls(table, col_name)


class _ForeignIndexType(_dtypes.Type):
    name = "foreignIndex"
    legacy_names = ["wandb.TableForeignIndex"]
    types = [_TableIndex]

    def __init__(self, table):
        assert isinstance(table, Table)
        self.params.update({"table": table})

    def assign_type(self, wb_type=None):
        if isinstance(wb_type, _dtypes.NumberType):
            return self
        elif isinstance(wb_type, _ForeignIndexType) and id(self.params["table"]) == id(
            wb_type.params["table"]
        ):
            return self

        return _dtypes.InvalidType()

    @classmethod
    def from_obj(cls, py_obj):
        if not isinstance(py_obj, _TableIndex):
            raise TypeError("py_obj must be a _TableIndex")
        else:
            return cls(py_obj._table)

    def to_json(self, artifact=None):
        res = super().to_json(artifact)
        if artifact is not None:
            table_name = f"media/tables/t_{runid.generate_id()}"
            entry = artifact.add(self.params["table"], table_name)
            res["params"]["table"] = entry.path
        else:
            raise AssertionError(
                "_ForeignIndexType does not support serialization without an artifact"
            )
        return res

    @classmethod
    def from_json(
        cls,
        json_dict,
        artifact,
    ):
        table = None
        if artifact is None:
            raise AssertionError(
                "_ForeignIndexType does not support deserialization without an artifact"
            )
        else:
            table = artifact.get(json_dict["params"]["table"])

        if table is None:
            raise AssertionError("Unable to deserialize referenced table")

        return cls(table)


_SUPPORTED_LOGGING_MODES = ["IMMUTABLE", "MUTABLE", "INCREMENTAL"]


class Table(Media):
    """The Table class used to display and analyze tabular data.

    Unlike traditional spreadsheets, Tables support numerous types of data:
    scalar values, strings, numpy arrays, and most subclasses of `wandb.data_types.Media`.
    This means you can embed `Images`, `Video`, `Audio`, and other sorts of rich, annotated media
    directly in Tables, alongside other traditional scalar values.

    This class is the primary class used to generate W&B Tables
    https://docs.wandb.ai/guides/models/tables/.
    """

    MAX_ROWS = 10000
    MAX_ARTIFACT_ROWS = 200000
    _MAX_EMBEDDING_DIMENSIONS = 150
    _log_type = "table"

    def __init__(
        self,
        columns=None,
        data=None,
        rows=None,
        dataframe=None,
        dtype=None,
        optional=True,
        allow_mixed_types=False,
        log_mode: Optional[
            Literal["IMMUTABLE", "MUTABLE", "INCREMENTAL"]
        ] = "IMMUTABLE",
    ):
        """Initializes a Table object.

        The rows is available for legacy reasons and should not be used.
        The Table class uses data to mimic the Pandas API.

        Args:
            columns: (List[str]) Names of the columns in the table.
                Defaults to ["Input", "Output", "Expected"].
            data: (List[List[any]]) 2D row-oriented array of values.
            dataframe: (pandas.DataFrame) DataFrame object used to create the table.
                When set, `data` and `columns` arguments are ignored.
            rows: (List[List[any]]) 2D row-oriented array of values.
            optional: (Union[bool,List[bool]]) Determines if `None` values are allowed. Default to True
                - If a singular bool value, then the optionality is enforced for all
                columns specified at construction time
                - If a list of bool values, then the optionality is applied to each
                column - should be the same length as `columns`
                applies to all columns. A list of bool values applies to each respective column.
            allow_mixed_types: (bool) Determines if columns are allowed to have mixed types
                (disables type validation). Defaults to False
            log_mode: Optional[str] Controls how the Table is logged when mutations occur.
                Options:
                - "IMMUTABLE" (default): Table can only be logged once; subsequent
                logging attempts after the table has been mutated will be no-ops.
                - "MUTABLE": Table can be re-logged after mutations, creating
                a new artifact version each time it's logged.
                - "INCREMENTAL": Table data is logged incrementally, with each log creating
                a new artifact entry containing the new data since the last log.
        """
        super().__init__()
        self._validate_log_mode(log_mode)
        self.log_mode = log_mode
        if self.log_mode == "INCREMENTAL":
            self._increment_num: int | None = None
            self._last_logged_idx: int | None = None
            self._previous_increments_paths: list[str] | None = None
            self._run_target_for_increments: LocalRun | None = None
        self._pk_col = None
        self._fk_cols: set[str] = set()
        if allow_mixed_types:
            dtype = _dtypes.AnyType

        # This is kept for legacy reasons (tss: personally, I think we should remove this)
        if columns is None:
            columns = ["Input", "Output", "Expected"]

        # Explicit dataframe option
        if dataframe is not None:
            self._init_from_dataframe(dataframe, columns, optional, dtype)
        else:
            # Expected pattern
            if data is not None:
                if util.is_numpy_array(data):
                    self._init_from_ndarray(data, columns, optional, dtype)
                elif util.is_pandas_data_frame(data):
                    self._init_from_dataframe(data, columns, optional, dtype)
                else:
                    self._init_from_list(data, columns, optional, dtype)

            # legacy
            elif rows is not None:
                self._init_from_list(rows, columns, optional, dtype)

            # Default empty case
            else:
                self._init_from_list([], columns, optional, dtype)

    def _validate_log_mode(self, log_mode):
        assert log_mode in _SUPPORTED_LOGGING_MODES, (
            f"Invalid log_mode: {log_mode}. Must be one of {_SUPPORTED_LOGGING_MODES}"
        )

    @staticmethod
    def _assert_valid_columns(columns):
        valid_col_types = [str, int]
        assert isinstance(columns, list), "columns argument expects a `list` object"
        assert len(columns) == 0 or all(
            [type(col) in valid_col_types for col in columns]
        ), "columns argument expects list of strings or ints"

    def _init_from_list(self, data, columns, optional=True, dtype=None):
        assert isinstance(data, list), "data argument expects a `list` object"
        self.data = []
        self._assert_valid_columns(columns)
        self.columns = columns
        self._make_column_types(dtype, optional)
        for row in data:
            self.add_data(*row)

    def _init_from_ndarray(self, ndarray, columns, optional=True, dtype=None):
        assert util.is_numpy_array(ndarray), (
            "ndarray argument expects a `numpy.ndarray` object"
        )
        self.data = []
        self._assert_valid_columns(columns)
        self.columns = columns
        self._make_column_types(dtype, optional)
        for row in ndarray:
            self.add_data(*row)

    def _init_from_dataframe(self, dataframe, columns, optional=True, dtype=None):
        assert util.is_pandas_data_frame(dataframe), (
            "dataframe argument expects a `pandas.core.frame.DataFrame` object"
        )
        self.data = []
        columns = list(dataframe.columns)
        self._assert_valid_columns(columns)
        self.columns = columns
        self._make_column_types(dtype, optional)
        for row in range(len(dataframe)):
            self.add_data(*tuple(dataframe[col].values[row] for col in self.columns))

    def _make_column_types(self, dtype=None, optional=True):
        if dtype is None:
            dtype = _dtypes.UnknownType()

        if optional.__class__ is not list:
            optional = [optional for _ in range(len(self.columns))]

        if dtype.__class__ is not list:
            dtype = [dtype for _ in range(len(self.columns))]

        self._column_types = _dtypes.TypedDictType({})
        for col_name, opt, dt in zip(self.columns, optional, dtype):
            self.cast(col_name, dt, opt)

    def _load_incremental_table_state_from_resumed_run(self, run: "LocalRun", key: str):
        """Handle updating incremental table state for resumed runs.

        This method is called when a run is resumed and there are previous
        increments of this table that need to be preserved. It updates the
        table's internal state to track previous increments and the current
        increment number.
        """
        if (
            self._previous_increments_paths is not None
            or self._increment_num is not None
        ):
            raise AssertionError(
                "The table has been initialized for a resumed run already"
            )

        self._set_incremental_table_run_target(run)

        summary_from_key = run.summary.get(key)

        if (
            summary_from_key is None
            or not isinstance(summary_from_key, dict)
            or summary_from_key.get("_type") != "incremental-table-file"
        ):
            # The key was never logged to the run or its last logged
            # value was not an incrementally logged table.
            return

        previous_increments_paths = summary_from_key.get(
            "previous_increments_paths", []
        )

        # add the artifact path of the last logged increment
        last_artifact_path = summary_from_key.get("artifact_path")

        if last_artifact_path:
            previous_increments_paths.append(last_artifact_path)

        # add 1 because a new increment is being logged
        last_increment_num = summary_from_key.get("increment_num", 0)

        self._increment_num = last_increment_num + 1
        self._previous_increments_paths = previous_increments_paths

    def _set_incremental_table_run_target(self, run: "LocalRun") -> None:
        """Associate a Run object with this incremental Table.

        A Table object in incremental mode can only be logged to a single Run.
        Raises an error if the table is already associated to a different run.
        """
        if self._run_target_for_increments is None:
            self._run_target_for_increments = run
        elif self._run_target_for_increments is not run:
            raise AssertionError("An incremental Table can only be logged to one Run.")

    @allow_relogging_after_mutation
    def cast(self, col_name, dtype, optional=False):
        """Casts a column to a specific data type.

        This can be one of the normal python classes, an internal W&B type,
        or an example object, like an instance of wandb.Image or
        wandb.Classes.

        Args:
            col_name (str): The name of the column to cast.
            dtype (class, wandb.wandb_sdk.interface._dtypes.Type, any): The
                target dtype.
            optional (bool): If the column should allow Nones.
        """
        assert col_name in self.columns

        wbtype = _dtypes.TypeRegistry.type_from_dtype(dtype)

        if optional:
            wbtype = _dtypes.OptionalType(wbtype)

        # Cast each value in the row, raising an error if there are invalid entries.
        col_ndx = self.columns.index(col_name)
        for row in self.data:
            result_type = wbtype.assign(row[col_ndx])
            if isinstance(result_type, _dtypes.InvalidType):
                raise TypeError(
                    f"Existing data {row[col_ndx]}, of type {_dtypes.TypeRegistry.type_of(row[col_ndx])} cannot be cast to {wbtype}"
                )
            wbtype = result_type

        # Assert valid options
        is_pk = isinstance(wbtype, _PrimaryKeyType)
        is_fk = isinstance(wbtype, _ForeignKeyType)
        is_fi = isinstance(wbtype, _ForeignIndexType)
        if is_pk or is_fk or is_fi:
            assert not optional, (
                "Primary keys, foreign keys, and foreign indexes cannot be optional."
            )

        if (is_fk or is_fk) and id(wbtype.params["table"]) == id(self):
            raise AssertionError("Cannot set a foreign table reference to same table.")

        if is_pk:
            assert self._pk_col is None, (
                f"Cannot have multiple primary keys - {self._pk_col} is already set as the primary key."
            )

        # Update the column type
        self._column_types.params["type_map"][col_name] = wbtype

        # Wrap the data if needed
        self._update_keys()
        return wbtype

    def __ne__(self, other):
        return not self.__eq__(other)

    def _eq_debug(self, other, should_assert=False):
        eq = isinstance(other, Table)
        assert not should_assert or eq, (
            f"Found type {other.__class__}, expected {Table}"
        )
        eq = eq and len(self.data) == len(other.data)
        assert not should_assert or eq, (
            f"Found {len(other.data)} rows, expected {len(self.data)}"
        )
        eq = eq and self.columns == other.columns
        assert not should_assert or eq, (
            f"Found columns {other.columns}, expected {self.columns}"
        )
        eq = eq and self._column_types == other._column_types
        assert not should_assert or eq, (
            f"Found column type {other._column_types}, expected column type {self._column_types}"
        )
        if eq:
            for row_ndx in range(len(self.data)):
                for col_ndx in range(len(self.data[row_ndx])):
                    _eq = self.data[row_ndx][col_ndx] == other.data[row_ndx][col_ndx]
                    # equal if all are equal
                    if util.is_numpy_array(_eq):
                        _eq = ((_eq * -1) + 1).sum() == 0
                    eq = eq and _eq
                    assert not should_assert or eq, (
                        f"Unequal data at row_ndx {row_ndx} col_ndx {col_ndx}: found {other.data[row_ndx][col_ndx]}, expected {self.data[row_ndx][col_ndx]}"
                    )
                    if not eq:
                        return eq
        return eq

    def __eq__(self, other):
        return self._eq_debug(other)

    @allow_relogging_after_mutation
    def add_row(self, *row):
        """Deprecated. Use `Table.add_data` method instead."""
        logging.warning("add_row is deprecated, use add_data")
        self.add_data(*row)

    @allow_relogging_after_mutation
    @allow_incremental_logging_after_append
    def add_data(self, *data):
        """Adds a new row of data to the table.

        The maximum amount ofrows in a table is determined by
        `wandb.Table.MAX_ARTIFACT_ROWS`.

        The length of the data should match the length of the table column.
        """
        if len(data) != len(self.columns):
            raise ValueError(
                f"This table expects {len(self.columns)} columns: {self.columns}, found {len(data)}"
            )

        # Special case to pre-emptively cast a column as a key.
        # Needed as String.assign(Key) is invalid
        for ndx, item in enumerate(data):
            if isinstance(item, _TableLinkMixin):
                self.cast(
                    self.columns[ndx],
                    _dtypes.TypeRegistry.type_of(item),
                    optional=False,
                )

        # Update the table's column types
        result_type = self._get_updated_result_type(data)
        self._column_types = result_type

        # rows need to be mutable
        if isinstance(data, tuple):
            data = list(data)
        # Add the new data
        self.data.append(data)

        # Update the wrapper values if needed
        self._update_keys(force_last=True)

    def _get_updated_result_type(self, row):
        """Returns the updated result type based on the inputted row.

        Raises:
            TypeError: if the assignment is invalid.
        """
        incoming_row_dict = {
            col_key: row[ndx] for ndx, col_key in enumerate(self.columns)
        }
        current_type = self._column_types
        result_type = current_type.assign(incoming_row_dict)
        if isinstance(result_type, _dtypes.InvalidType):
            raise TypeError(
                f"Data row contained incompatible types:\n{current_type.explain(incoming_row_dict)}"
            )
        return result_type

    def _to_table_json(self, max_rows=None, warn=True):
        # separate this method for easier testing
        if max_rows is None:
            max_rows = Table.MAX_ROWS
        n_rows = len(self.data)
        if n_rows > max_rows and warn:
            # NOTE: Never raises for reinit="create_new" runs.
            #   Since this is called by bind_to_run(), this can be fixed by
            #   propagating the run. It cannot be fixed for to_json() calls
            #   that are given an artifact, other than by deferring to singleton
            #   settings.
            if wandb.run and (
                wandb.run.settings.table_raise_on_max_row_limit_exceeded
                or wandb.run.settings.strict
            ):
                raise ValueError(
                    f"Table row limit exceeded: table has {n_rows} rows, limit is {max_rows}. "
                    f"To increase the maximum number of allowed rows in a wandb.Table, override "
                    f"the limit with `wandb.Table.MAX_ARTIFACT_ROWS = X` and try again. Note: "
                    f"this may cause slower queries in the W&B UI."
                )
            logging.warning(f"Truncating wandb.Table object to {max_rows} rows.")

        if self.log_mode == "INCREMENTAL" and self._last_logged_idx is not None:
            return {
                "columns": self.columns,
                "data": self.data[
                    self._last_logged_idx + 1 : self._last_logged_idx + 1 + max_rows
                ],
            }
        else:
            return {"columns": self.columns, "data": self.data[:max_rows]}

    def bind_to_run(self, *args, **kwargs):
        """Bind this object to a run.

        <!-- lazydoc-ignore: internal -->
        """
        # We set `warn=False` since Tables will now always be logged to both
        # files and artifacts. The file limit will never practically matter and
        # this code path will be ultimately removed. The 10k limit warning confuses
        # users given that we publicly say 200k is the limit.
        data = self._to_table_json(warn=False)
        tmp_path = os.path.join(MEDIA_TMP.name, runid.generate_id() + ".table.json")
        data = _numpy_arrays_to_lists(data)
        with codecs.open(tmp_path, "w", encoding="utf-8") as fp:
            util.json_dump_safer(data, fp)
        self._set_file(tmp_path, is_tmp=True, extension=".table.json")
        super().bind_to_run(*args, **kwargs)

    @classmethod
    def get_media_subdir(cls):
        """Get media subdirectory.

        <!-- lazydoc-ignore-classmethod: internal -->
        """
        return os.path.join("media", "table")

    @classmethod
    def from_json(cls, json_obj, source_artifact: "artifact.Artifact"):
        """Deserialize JSON object into it's class representation.

        <!-- lazydoc-ignore-classmethod: internal -->
        """
        data = []
        column_types = None
        np_deserialized_columns = {}
        timestamp_column_indices = set()
        log_mode = json_obj.get("log_mode", "IMMUTABLE")
        if json_obj.get("column_types") is not None:
            column_types = _dtypes.TypeRegistry.type_from_dict(
                json_obj["column_types"], source_artifact
            )
            for col_name in column_types.params["type_map"]:
                col_type = column_types.params["type_map"][col_name]
                ndarray_type = None
                if isinstance(col_type, _dtypes.NDArrayType):
                    ndarray_type = col_type
                elif isinstance(col_type, _dtypes.UnionType):
                    for t in col_type.params["allowed_types"]:
                        if isinstance(t, _dtypes.NDArrayType):
                            ndarray_type = t
                        elif isinstance(t, _dtypes.TimestampType):
                            timestamp_column_indices.add(
                                json_obj["columns"].index(col_name)
                            )

                elif isinstance(col_type, _dtypes.TimestampType):
                    timestamp_column_indices.add(json_obj["columns"].index(col_name))

                if (
                    ndarray_type is not None
                    and ndarray_type._get_serialization_path() is not None
                ):
                    serialization_path = ndarray_type._get_serialization_path()

                    if serialization_path is None:
                        continue

                    np = util.get_module(
                        "numpy",
                        required="Deserializing NumPy columns requires NumPy to be installed.",
                    )
                    deserialized = np.load(
                        source_artifact.get_entry(serialization_path["path"]).download()
                    )
                    np_deserialized_columns[json_obj["columns"].index(col_name)] = (
                        deserialized[serialization_path["key"]]
                    )
                    ndarray_type._clear_serialization_path()

        if log_mode == "INCREMENTAL":
            unprocessed_table_data = _get_data_from_increments(
                json_obj, source_artifact
            )
        else:
            unprocessed_table_data = json_obj["data"]

        for r_ndx, row in enumerate(unprocessed_table_data):
            data.append(
                _process_table_row(
                    row,
                    timestamp_column_indices,
                    np_deserialized_columns,
                    source_artifact,
                    r_ndx,
                )
            )

        # construct Table with dtypes for each column if type information exists
        dtypes = None
        if column_types is not None:
            dtypes = [
                column_types.params["type_map"][str(col)] for col in json_obj["columns"]
            ]

        new_obj = cls(
            columns=json_obj["columns"], data=data, dtype=dtypes, log_mode=log_mode
        )

        if column_types is not None:
            new_obj._column_types = column_types

        new_obj._update_keys()
        return new_obj

    def to_json(self, run_or_artifact):
        """Returns the JSON representation expected by the backend.

        <!-- lazydoc-ignore: internal -->
        """
        json_dict = super().to_json(run_or_artifact)

        if self.log_mode == "INCREMENTAL":
            if self._previous_increments_paths is None:
                self._previous_increments_paths = []
            if self._increment_num is None:
                self._increment_num = 0

            json_dict.update(
                {
                    "increment_num": self._increment_num,
                    "previous_increments_paths": self._previous_increments_paths,
                }
            )

        if isinstance(run_or_artifact, wandb.Run):
            if self.log_mode == "INCREMENTAL":
                wbvalue_type = "incremental-table-file"
            else:
                wbvalue_type = "table-file"

            json_dict.update(
                {
                    "_type": wbvalue_type,
                    "ncols": len(self.columns),
                    "nrows": len(self.data),
                    "log_mode": self.log_mode,
                }
            )

        elif isinstance(run_or_artifact, wandb.Artifact):
            artifact = run_or_artifact
            mapped_data = []
            data = self._to_table_json(Table.MAX_ARTIFACT_ROWS)["data"]

            ndarray_col_ndxs = set()
            for col_ndx, col_name in enumerate(self.columns):
                col_type = self._column_types.params["type_map"][col_name]
                ndarray_type = None
                if isinstance(col_type, _dtypes.NDArrayType):
                    ndarray_type = col_type
                elif isinstance(col_type, _dtypes.UnionType):
                    for t in col_type.params["allowed_types"]:
                        if isinstance(t, _dtypes.NDArrayType):
                            ndarray_type = t

                # Do not serialize 1d arrays - these are likely embeddings and
                # will not have the same cost as higher dimensional arrays
                is_1d_array = (
                    ndarray_type is not None
                    and "shape" in ndarray_type._params
                    and isinstance(ndarray_type._params["shape"], list)
                    and len(ndarray_type._params["shape"]) == 1
                    and ndarray_type._params["shape"][0]
                    <= self._MAX_EMBEDDING_DIMENSIONS
                )
                if is_1d_array:
                    self._column_types.params["type_map"][col_name] = _dtypes.ListType(
                        _dtypes.NumberType, ndarray_type._params["shape"][0]
                    )
                elif ndarray_type is not None:
                    np = util.get_module(
                        "numpy",
                        required="Serializing NumPy requires NumPy to be installed.",
                    )
                    file_name = f"{str(col_name)}_{runid.generate_id()}.npz"
                    npz_file_name = os.path.join(MEDIA_TMP.name, file_name)
                    np.savez_compressed(
                        npz_file_name,
                        **{
                            str(col_name): self.get_column(col_name, convert_to="numpy")
                        },
                    )
                    entry = artifact.add_file(
                        npz_file_name, "media/serialized_data/" + file_name, is_tmp=True
                    )
                    ndarray_type._set_serialization_path(entry.path, str(col_name))
                    ndarray_col_ndxs.add(col_ndx)

            for row in data:
                mapped_row = []
                for ndx, v in enumerate(row):
                    if ndx in ndarray_col_ndxs:
                        mapped_row.append(None)
                    else:
                        mapped_row.append(_json_helper(v, artifact))
                mapped_data.append(mapped_row)

            json_dict.update(
                {
                    "_type": Table._log_type,
                    "columns": self.columns,
                    "data": mapped_data,
                    "ncols": len(self.columns),
                    "nrows": len(mapped_data),
                    "column_types": self._column_types.to_json(artifact),
                    "log_mode": self.log_mode,
                }
            )
        else:
            raise TypeError("to_json accepts wandb_run.Run or wandb_artifact.Artifact")

        return json_dict

    def iterrows(self):
        """Returns the table data by row, showing the index of the row and the relevant data.

        Yields:
        ------
        index: The index of the row. Using this value in other W&B tables
            will automatically build a relationship between the tables
        row: The data of the row.

        <!-- lazydoc-ignore: internal -->
        """
        for ndx in range(len(self.data)):
            index = _TableIndex(ndx)
            index.set_table(self)
            yield index, self.data[ndx]

    @allow_relogging_after_mutation
    def set_pk(self, col_name):
        """Set primary key type for Table object.

        <!-- lazydoc-ignore: internal -->
        """
        # TODO: Docs
        assert col_name in self.columns
        self.cast(col_name, _PrimaryKeyType())

    @allow_relogging_after_mutation
    def set_fk(self, col_name, table, table_col):
        """Set foreign key type for Table object.

        <!-- lazydoc-ignore: internal -->
        """
        # TODO: Docs
        assert col_name in self.columns
        assert col_name != self._pk_col
        self.cast(col_name, _ForeignKeyType(table, table_col))

    def _update_keys(self, force_last=False):
        """Updates the known key-like columns based on current column types.

        If the state has been updated since the last update, wraps the data
        appropriately in the Key classes.

        Args:
            force_last: (bool) Wraps the last column of data even if there
                are no key updates.
        """
        _pk_col = None
        _fk_cols = set()

        # Buildup the known keys from column types
        c_types = self._column_types.params["type_map"]
        for t in c_types:
            if isinstance(c_types[t], _PrimaryKeyType):
                _pk_col = t
            elif isinstance(c_types[t], _ForeignKeyType) or isinstance(
                c_types[t], _ForeignIndexType
            ):
                _fk_cols.add(t)

        # If there are updates to perform, safely update them
        has_update = _pk_col != self._pk_col or _fk_cols != self._fk_cols
        if has_update:
            # If we removed the PK
            if _pk_col is None and self._pk_col is not None:
                raise AssertionError(
                    f"Cannot unset primary key (column {self._pk_col})"
                )
            # If there is a removed FK
            if len(self._fk_cols - _fk_cols) > 0:
                raise AssertionError(
                    f"Cannot unset foreign key. Attempted to unset ({self._fk_cols - _fk_cols})"
                )

            self._pk_col = _pk_col
            self._fk_cols = _fk_cols

        # Apply updates to data only if there are update or the caller
        # requested the final row to be updated
        if has_update or force_last:
            self._apply_key_updates(not has_update)

    def _apply_key_updates(self, only_last=False):
        """Appropriately wraps the underlying data in special Key classes.

        Args:
            only_last: only apply the updates to the last row (used for performance when
            the caller knows that the only new data is the last row and no updates were
            applied to the column types)
        """
        c_types = self._column_types.params["type_map"]

        # Define a helper function which will wrap the data of a single row
        # in the appropriate class wrapper.
        def update_row(row_ndx):
            for fk_col in self._fk_cols:
                col_ndx = self.columns.index(fk_col)

                # Wrap the Foreign Keys
                if isinstance(c_types[fk_col], _ForeignKeyType) and not isinstance(
                    self.data[row_ndx][col_ndx], _TableKey
                ):
                    self.data[row_ndx][col_ndx] = _TableKey(self.data[row_ndx][col_ndx])
                    self.data[row_ndx][col_ndx].set_table(
                        c_types[fk_col].params["table"],
                        c_types[fk_col].params["col_name"],
                    )

                # Wrap the Foreign Indexes
                elif isinstance(c_types[fk_col], _ForeignIndexType) and not isinstance(
                    self.data[row_ndx][col_ndx], _TableIndex
                ):
                    self.data[row_ndx][col_ndx] = _TableIndex(
                        self.data[row_ndx][col_ndx]
                    )
                    self.data[row_ndx][col_ndx].set_table(
                        c_types[fk_col].params["table"]
                    )

            # Wrap the Primary Key
            if self._pk_col is not None:
                col_ndx = self.columns.index(self._pk_col)
                self.data[row_ndx][col_ndx] = _TableKey(self.data[row_ndx][col_ndx])
                self.data[row_ndx][col_ndx].set_table(self, self._pk_col)

        if only_last:
            update_row(len(self.data) - 1)
        else:
            for row_ndx in range(len(self.data)):
                update_row(row_ndx)

    @ensure_not_incremental
    @allow_relogging_after_mutation
    def add_column(self, name, data, optional=False):
        """Adds a column of data to the table.

        Args:
            name: (str) - the unique name of the column
            data: (list | np.array) - a column of homogeneous data
            optional: (bool) - if null-like values are permitted
        """
        assert isinstance(name, str) and name not in self.columns
        is_np = util.is_numpy_array(data)
        assert isinstance(data, list) or is_np
        assert isinstance(optional, bool)
        is_first_col = len(self.columns) == 0
        assert is_first_col or len(data) == len(self.data), (
            f"Expected length {len(self.data)}, found {len(data)}"
        )

        # Add the new data
        for ndx in range(max(len(data), len(self.data))):
            if is_first_col:
                self.data.append([])
            if is_np:
                self.data[ndx].append(data[ndx])
            else:
                self.data[ndx].append(data[ndx])
        # add the column
        self.columns.append(name)

        try:
            self.cast(name, _dtypes.UnknownType(), optional=optional)
        except TypeError:
            # Undo the changes
            if is_first_col:
                self.data = []
                self.columns = []
            else:
                for ndx in range(len(self.data)):
                    self.data[ndx] = self.data[ndx][:-1]
                self.columns = self.columns[:-1]
            raise

    def get_column(self, name, convert_to=None):
        """Retrieves a column from the table and optionally converts it to a NumPy object.

        Args:
            name: (str) - the name of the column
            convert_to: (str, optional)
                - "numpy": will convert the underlying data to numpy object
        """
        assert name in self.columns
        assert convert_to is None or convert_to == "numpy"
        if convert_to == "numpy":
            np = util.get_module(
                "numpy", required="Converting to NumPy requires installing NumPy"
            )
        col = []
        col_ndx = self.columns.index(name)
        for row in self.data:
            item = row[col_ndx]
            if convert_to is not None and isinstance(item, WBValue):
                item = item.to_data_array()
            col.append(item)
        if convert_to == "numpy":
            col = np.array(col)
        return col

    def get_index(self):
        """Returns an array of row indexes for use in other tables to create links."""
        ndxs = []
        for ndx in range(len(self.data)):
            index = _TableIndex(ndx)
            index.set_table(self)
            ndxs.append(index)
        return ndxs

    def get_dataframe(self):
        """Returns a `pandas.DataFrame` of the table."""
        pd = util.get_module(
            "pandas",
            required="Converting to pandas.DataFrame requires installing pandas",
        )
        return pd.DataFrame.from_records(self.data, columns=self.columns)

    def index_ref(self, index):
        """Gets a reference of the index of a row in the table.

        <!-- lazydoc-ignore: internal -->
        """
        assert index < len(self.data)
        _index = _TableIndex(index)
        _index.set_table(self)
        return _index

    @ensure_not_incremental
    @allow_relogging_after_mutation
    def add_computed_columns(self, fn):
        """Adds one or more computed columns based on existing data.

        Args:
            fn: A function which accepts one or two parameters, ndx (int) and
                row (dict), which is expected to return a dict representing
                new columns for that row, keyed by the new column names.
            - `ndx` is an integer representing the index of the row. Only included if `include_ndx`
                      is set to `True`.
            - `row` is a dictionary keyed by existing columns
        """
        new_columns = {}
        for ndx, row in self.iterrows():
            row_dict = {self.columns[i]: row[i] for i in range(len(self.columns))}
            new_row_dict = fn(ndx, row_dict)
            assert isinstance(new_row_dict, dict)
            for key in new_row_dict:
                new_columns[key] = new_columns.get(key, [])
                new_columns[key].append(new_row_dict[key])
        for new_col_name in new_columns:
            self.add_column(new_col_name, new_columns[new_col_name])


class _PartitionTablePartEntry:
    """Helper class for PartitionTable to track its parts."""

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
    """A table which is composed of multiple sub-tables.

    Currently, PartitionedTable is designed to point to a directory within an
    artifact.
    """

    _log_type = "partitioned-table"

    def __init__(self, parts_path):
        """Initialize a PartitionedTable.

        Args:
            parts_path (str): path to a directory of tables in the artifact.
        """
        super().__init__()
        self.parts_path = parts_path
        self._loaded_part_entries = {}

    def to_json(self, artifact_or_run):
        json_obj = {
            "_type": PartitionedTable._log_type,
        }
        if isinstance(artifact_or_run, wandb.Run):
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
        """Iterate over rows as (ndx, row).

        Args:
            index (int): The index of the row.
            row (List[any]): The data of the row.
        """
        columns = None
        ndx = 0
        for entry_path in self._loaded_part_entries:
            part = self._loaded_part_entries[entry_path].get_part()
            if columns is None:
                columns = part.columns
            elif columns != part.columns:
                raise ValueError(
                    f"Table parts have non-matching columns. {columns} != {part.columns}"
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


class JoinedTable(Media):
    """Join two tables for visualization in the Artifact UI.

    Args:
        table1 (str, wandb.Table, ArtifactManifestEntry):
            the path to a wandb.Table in an artifact, the table object, or ArtifactManifestEntry
        table2 (str, wandb.Table):
            the path to a wandb.Table in an artifact, the table object, or ArtifactManifestEntry
        join_key (str, [str, str]):
            key or keys to perform the join
    """

    _log_type = "joined-table"

    def __init__(self, table1, table2, join_key):
        super().__init__()

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
        """Helper method to validate that the table input is one of the 3 supported types."""
        return (
            (isinstance(table, str) and table.endswith(".table.json"))
            or isinstance(table, Table)
            or isinstance(table, PartitionedTable)
            or (hasattr(table, "ref_url") and table.ref_url().endswith(".table.json"))
        )

    def _ensure_table_in_artifact(self, table, artifact, table_ndx):
        """Helper method to add the table to the incoming artifact. Returns the path."""
        if isinstance(table, Table) or isinstance(table, PartitionedTable):
            table_name = f"t{table_ndx}_{str(id(self))}"
            if (
                table._artifact_source is not None
                and table._artifact_source.name is not None
            ):
                table_name = os.path.basename(table._artifact_source.name)
            entry = artifact.add(table, table_name)
            table = entry.path
        # Check if this is an ArtifactManifestEntry
        elif hasattr(table, "ref_url"):
            # Give the new object a unique, yet deterministic name
            name = binascii.hexlify(base64.standard_b64decode(table.digest)).decode(
                "ascii"
            )[:20]
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
        if isinstance(artifact_or_run, wandb.Run):
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
        assert not should_assert or eq, (
            f"Found type {other.__class__}, expected {JoinedTable}"
        )
        eq = eq and self._join_key == other._join_key
        assert not should_assert or eq, (
            f"Found {other._join_key} join key, expected {self._join_key}"
        )
        eq = eq and self._table1._eq_debug(other._table1, should_assert)
        eq = eq and self._table2._eq_debug(other._table2, should_assert)
        return eq

    def __eq__(self, other):
        return self._eq_debug(other, False)

    def bind_to_run(self, *args, **kwargs):
        raise ValueError("JoinedTables cannot be bound to runs")


class _TableType(_dtypes.Type):
    name = "table"
    legacy_names = ["wandb.Table"]
    types = [Table]

    def __init__(self, column_types=None):
        if column_types is None:
            column_types = _dtypes.UnknownType()
        if isinstance(column_types, dict):
            column_types = _dtypes.TypedDictType(column_types)
        elif not (
            isinstance(column_types, _dtypes.TypedDictType)
            or isinstance(column_types, _dtypes.UnknownType)
        ):
            raise TypeError("column_types must be a dict or TypedDictType")

        self.params.update({"column_types": column_types})

    def assign_type(self, wb_type=None):
        if isinstance(wb_type, _TableType):
            column_types = self.params["column_types"].assign_type(
                wb_type.params["column_types"]
            )
            if not isinstance(column_types, _dtypes.InvalidType):
                return _TableType(column_types)

        return _dtypes.InvalidType()

    @classmethod
    def from_obj(cls, py_obj):
        if not isinstance(py_obj, Table):
            raise TypeError("py_obj must be a wandb.Table")
        else:
            return cls(py_obj._column_types)


class _JoinedTableType(_dtypes.Type):
    name = "joined-table"
    types = [JoinedTable]


class _PartitionedTableType(_dtypes.Type):
    name = "partitioned-table"
    types = [PartitionedTable]


_dtypes.TypeRegistry.add(_TableType)
_dtypes.TypeRegistry.add(_JoinedTableType)
_dtypes.TypeRegistry.add(_PartitionedTableType)
_dtypes.TypeRegistry.add(_ForeignKeyType)
_dtypes.TypeRegistry.add(_PrimaryKeyType)
_dtypes.TypeRegistry.add(_ForeignIndexType)


def _get_data_from_increments(
    json_obj: Dict[str, Any], source_artifact: "artifact.Artifact"
) -> List[Any]:
    """Get data from incremental table artifacts.

    Args:
        json_obj: The JSON object containing table metadata.
        source_artifact: The source artifact containing the table data.

    Returns:
        List of table rows from all increments.
    """
    if "latest" not in source_artifact.aliases:
        wandb.termwarn(
            (
                "It is recommended to use the latest version of the "
                "incremental table artifact for ordering guarantees."
            ),
            repeat=False,
        )
    data: List[Any] = []
    increment_num = json_obj.get("increment_num", None)
    if increment_num is None:
        return data

    # Sort by increment number first, then by timestamp if present
    # Format of name is: "{incr_num}-{timestamp_ms}.{key}.table.json"
    def get_sort_key(key: str) -> Tuple[int, int]:
        try:
            parts = key.split(".")
            increment_parts = parts[0].split("-")
            increment_num = int(increment_parts[0])
            # If there's a timestamp part, use it for secondary sorting
            timestamp = int(increment_parts[1]) if len(increment_parts) > 1 else 0
        except (ValueError, IndexError):
            wandb.termwarn(
                (
                    f"Could not parse artifact entry for increment {key}."
                    " The entry name does not follow the naming convention"
                    " <increment_number>-<timestamp>.<key>.table.json"
                    " The data in the table will be out of order."
                ),
                repeat=False,
            )
            return (0, 0)

        return (increment_num, timestamp)

    sorted_increment_keys = []
    for entry_key in source_artifact.manifest.entries:
        if entry_key.endswith(".table.json"):
            sorted_increment_keys.append(entry_key)

    sorted_increment_keys.sort(key=get_sort_key)

    for entry_key in sorted_increment_keys:
        try:
            with open(source_artifact.manifest.entries[entry_key].download()) as f:
                table_data = json.load(f)
            data.extend(table_data["data"])
        except (json.JSONDecodeError, KeyError) as e:
            raise wandb.Error(f"Invalid table file {entry_key}") from e
    return data


def _process_table_row(
    row: List[Any],
    timestamp_column_indices: Set[_dtypes.TimestampType],
    np_deserialized_columns: Dict[int, Any],
    source_artifact: "artifact.Artifact",
    row_idx: int,
) -> List[Any]:
    """Convert special columns in a table row to Python types.

    Processes a single row of table data by converting timestamp values to
    datetime objects, replacing np typed cells with numpy array data,
    and initializing media objects from their json value.


    Args:
        row: The row data to process.
        timestamp_column_indices: Set of column indices containing timestamps.
        np_deserialized_columns: Dictionary mapping column indices to numpy arrays.
        source_artifact: The source artifact containing the table data.
        row_idx: The index of the current row.

    Returns:
        Processed row data.
    """
    row_data = []
    for c_ndx, item in enumerate(row):
        cell: Any
        if c_ndx in timestamp_column_indices and isinstance(item, (int, float)):
            cell = datetime.datetime.fromtimestamp(
                item / 1000, tz=datetime.timezone.utc
            )
        elif c_ndx in np_deserialized_columns:
            cell = np_deserialized_columns[c_ndx][row_idx]
        elif (
            isinstance(item, dict)
            and "_type" in item
            and (obj := WBValue.init_from_json(item, source_artifact))
        ):
            cell = obj
        else:
            cell = item
        row_data.append(cell)
    return row_data
