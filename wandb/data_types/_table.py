import codecs
import logging
import os

import wandb
from wandb.sdk.interface import _dtypes
from wandb.util import (
    generate_id,
    get_module,
    is_numpy_array,
    is_pandas_data_frame,
    json_dump_safer,
    json_friendly,
)

from ._media import Media
from ._wandb_value import WBValue
from .utils import _numpy_arrays_to_lists


def _json_helper(val, artifact):
    if isinstance(val, WBValue):
        return val.to_json(artifact)
    elif val.__class__ == dict:
        res = {}
        for key in val:
            res[key] = _json_helper(val[key], artifact)
        return res
    elif hasattr(val, "tolist"):
        return json_friendly(val.tolist())[0]
    else:
        return json_friendly(val)[0]


class _TableLinkMixin(object):
    def set_table(self, table):
        self._table = table


class _TableIndex(int, _TableLinkMixin):
    def get_row(self):
        row = {}
        if self._table:
            row = {
                c: self._table.data[self][i] for i, c in enumerate(self._table.columns)
            }

        return row


class _TableKey(str, _TableLinkMixin):
    def set_table(self, table, col_name):
        assert col_name in table.columns
        self._table = table
        self._col_name = col_name


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


class Table(Media):
    """The Table class is used to display and analyze tabular data.

    Unlike traditional spreadsheets, Tables support numerous types of data:
    scalar values, strings, numpy arrays, and most subclasses of `wandb.data_types.Media`.
    This means you can embed `Images`, `Video`, `Audio`, and other sorts of rich, annotated media
    directly in Tables, alongside other traditional scalar values.

    This class is the primary class used to generate the Table Visualizer
    in the UI: https://docs.wandb.ai/guides/data-vis/tables.

    Tables can be constructed with initial data using the `data` or
    `dataframe` parameters:
    <!--yeadoc-test:table-construct-dataframe-->
    ```python
    import pandas as pd
    import wandb

    data = {"users": ["geoff", "juergen", "ada"],
            "feature_01": [1, 117, 42]}
    df = pd.DataFrame(data)

    tbl = wandb.Table(data=df)
    assert all(tbl.get_column("users") == df["users"])
    assert all(tbl.get_column("feature_01") == df["feature_01"])
    ```

    Additionally, users can add data to Tables incrementally by using the
    `add_data`, `add_column`, and `add_computed_column` functions for
    adding rows, columns, and columns computed from data in other columns, respectively:
    <!--yeadoc-test:table-construct-rowwise-->
    ```python
    import wandb

    tbl = wandb.Table(columns=["user"])

    users = ["geoff", "juergen", "ada"]

    [tbl.add_data(user) for user in users]
    assert tbl.get_column("user") == users

    def get_user_name_length(index, row): return {"feature_01": len(row["user"])}
    tbl.add_computed_columns(get_user_name_length)
    assert tbl.get_column("feature_01") == [5, 7, 3]
    ```

    Tables can be logged directly to runs using `run.log({"my_table": table})`
    or added to artifacts using `artifact.add(table, "my_table")`:
    <!--yeadoc-test:table-logging-direct-->
    ```python
    import numpy as np
    import wandb

    wandb.init()

    tbl = wandb.Table(columns=["image", "label"])

    images = np.random.randint(0, 255, [2, 100, 100, 3], dtype=np.uint8)
    labels = ["panda", "gibbon"]
    [tbl.add_data(wandb.Image(image), label) for image, label in zip(images, labels)]

    wandb.log({"classifier_out": tbl})
    ```

    Tables added directly to runs as above will produce a corresponding Table Visualizer in the
    Workspace which can be used for further analysis and exporting to reports.

    Tables added to artifacts can be viewed in the Artifact Tab and will render
    an equivalent Table Visualizer directly in the artifact browser.

    Tables expect each value for a column to be of the same type. By default, a column supports
    optional values, but not mixed values. If you absolutely need to mix types,
    you can enable the `allow_mixed_types` flag which will disable type checking
    on the data. This will result in some table analytics features being disabled
    due to lack of consistent typing.

    Arguments:
        columns: (List[str]) Names of the columns in the table.
            Defaults to ["Input", "Output", "Expected"].
        data: (List[List[any]]) 2D row-oriented array of values.
        dataframe: (pandas.DataFrame) DataFrame object used to create the table.
            When set, `data` and `columns` arguments are ignored.
        optional: (Union[bool,List[bool]]) Determines if `None` values are allowed. Default to True
            - If a singular bool value, then the optionality is enforced for all
            columns specified at construction time
            - If a list of bool values, then the optionality is applied to each
            column - should be the same length as `columns`
            applies to all columns. A list of bool values applies to each respective column.
        allow_mixed_types: (bool) Determines if columns are allowed to have mixed types
            (disables type validation). Defaults to False
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
    ):
        """rows is kept for legacy reasons, we use data to mimic the Pandas api"""
        super(Table, self).__init__()
        self._pk_col = None
        self._fk_cols = set()
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
                if is_numpy_array(data):
                    self._init_from_ndarray(data, columns, optional, dtype)
                elif is_pandas_data_frame(data):
                    self._init_from_dataframe(data, columns, optional, dtype)
                else:
                    self._init_from_list(data, columns, optional, dtype)

            # legacy
            elif rows is not None:
                self._init_from_list(rows, columns, optional, dtype)

            # Default empty case
            else:
                self._init_from_list([], columns, optional, dtype)

    @staticmethod
    def _assert_valid_columns(columns):
        valid_col_types = [str, int]
        assert type(columns) is list, "columns argument expects a `list` object"
        assert len(columns) == 0 or all(
            [type(col) in valid_col_types for col in columns]
        ), "columns argument expects list of strings or ints"

    def _init_from_list(self, data, columns, optional=True, dtype=None):
        assert type(data) is list, "data argument expects a `list` object"
        self.data = []
        self._assert_valid_columns(columns)
        self.columns = columns
        self._make_column_types(dtype, optional)
        for row in data:
            self.add_data(*row)

    def _init_from_ndarray(self, ndarray, columns, optional=True, dtype=None):
        assert is_numpy_array(
            ndarray
        ), "ndarray argument expects a `numpy.ndarray` object"
        self.data = []
        self._assert_valid_columns(columns)
        self.columns = columns
        self._make_column_types(dtype, optional)
        for row in ndarray:
            self.add_data(*row)

    def _init_from_dataframe(self, dataframe, columns, optional=True, dtype=None):
        assert is_pandas_data_frame(
            dataframe
        ), "dataframe argument expects a `pandas.core.frame.DataFrame` object"
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

        if optional.__class__ != list:
            optional = [optional for _ in range(len(self.columns))]

        if dtype.__class__ != list:
            dtype = [dtype for _ in range(len(self.columns))]

        self._column_types = _dtypes.TypedDictType({})
        for col_name, opt, dt in zip(self.columns, optional, dtype):
            self.cast(col_name, dt, opt)

    def cast(self, col_name, dtype, optional=False):
        """Casts a column to a specific type

        Arguments:
            col_name: (str) - name of the column to cast
            dtype: (class, wandb.wandb_sdk.interface._dtypes.Type, any) - the target dtype. Can be one of
                normal python class, internal WB type, or an example object (eg. an instance of wandb.Image or wandb.Classes)
            optional: (bool) - if the column should allow Nones
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
                    "Existing data {}, of type {} cannot be cast to {}".format(
                        row[col_ndx],
                        _dtypes.TypeRegistry.type_of(row[col_ndx]),
                        wbtype,
                    )
                )
            wbtype = result_type

        # Assert valid options
        is_pk = isinstance(wbtype, _PrimaryKeyType)
        is_fk = isinstance(wbtype, _ForeignKeyType)
        is_fi = isinstance(wbtype, _ForeignIndexType)
        if is_pk or is_fk or is_fi:
            assert (
                not optional
            ), "Primary keys, foreign keys, and foreign indexes cannot be optional"

        if (is_fk or is_fk) and id(wbtype.params["table"]) == id(self):
            raise AssertionError("Cannot set a foreign table reference to same table")

        if is_pk:
            assert (
                self._pk_col is None
            ), "Cannot have multiple primary keys - {} is already set as the primary key.".format(
                self._pk_col
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
        assert not should_assert or eq, "Found type {}, expected {}".format(
            other.__class__, Table
        )
        eq = eq and len(self.data) == len(other.data)
        assert not should_assert or eq, "Found {} rows, expected {}".format(
            len(other.data), len(self.data)
        )
        eq = eq and self.columns == other.columns
        assert not should_assert or eq, "Found columns {}, expected {}".format(
            other.columns, self.columns
        )
        eq = eq and self._column_types == other._column_types
        assert (
            not should_assert or eq
        ), "Found column type {}, expected column type {}".format(
            other._column_types, self._column_types
        )
        if eq:
            for row_ndx in range(len(self.data)):
                for col_ndx in range(len(self.data[row_ndx])):
                    _eq = self.data[row_ndx][col_ndx] == other.data[row_ndx][col_ndx]
                    # equal if all are equal
                    if is_numpy_array(_eq):
                        _eq = ((_eq * -1) + 1).sum() == 0
                    eq = eq and _eq
                    assert (
                        not should_assert or eq
                    ), "Unequal data at row_ndx {} col_ndx {}: found {}, expected {}".format(
                        row_ndx,
                        col_ndx,
                        other.data[row_ndx][col_ndx],
                        self.data[row_ndx][col_ndx],
                    )
                    if not eq:
                        return eq
        return eq

    def __eq__(self, other):
        return self._eq_debug(other)

    def add_row(self, *row):
        logging.warning("add_row is deprecated, use add_data")
        self.add_data(*row)

    def add_data(self, *data):
        """Add a row of data to the table. Argument length should match column length"""
        if len(data) != len(self.columns):
            raise ValueError(
                "This table expects {} columns: {}, found {}".format(
                    len(self.columns), self.columns, len(data)
                )
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
        """Returns an updated result type based on incoming row. Raises error if
        the assignment is invalid"""
        incoming_row_dict = {
            col_key: row[ndx] for ndx, col_key in enumerate(self.columns)
        }
        current_type = self._column_types
        result_type = current_type.assign(incoming_row_dict)
        if isinstance(result_type, _dtypes.InvalidType):
            raise TypeError(
                "Data row contained incompatible types:\n{}".format(
                    current_type.explain(incoming_row_dict)
                )
            )
        return result_type

    def _to_table_json(self, max_rows=None, warn=True):
        # separate this method for easier testing
        if max_rows is None:
            max_rows = Table.MAX_ROWS
        if len(self.data) > max_rows and warn:
            logging.warning("Truncating wandb.Table object to %i rows." % max_rows)
        return {"columns": self.columns, "data": self.data[:max_rows]}

    def bind_to_run(self, *args, **kwargs):
        # We set `warn=False` since Tables will now always be logged to both
        # files and artifacts. The file limit will never practically matter and
        # this code path will be ultimately removed. The 10k limit warning confuses
        # users given that we publically say 200k is the limit.
        data = self._to_table_json(warn=False)
        tmp_path = os.path.join(self._MEDIA_TMP.name, generate_id() + ".table.json")
        data = _numpy_arrays_to_lists(data)
        with codecs.open(tmp_path, "w", encoding="utf-8") as fp:
            json_dump_safer(data, fp)
        self._set_file(tmp_path, is_tmp=True, extension=".table.json")
        super(Table, self).bind_to_run(*args, **kwargs)

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "table")

    @classmethod
    def from_json(cls, json_obj, source_artifact):
        data = []
        column_types = None
        np_deserialized_columns = {}
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
                if (
                    ndarray_type is not None
                    and ndarray_type._get_serialization_path() is not None
                ):
                    serialization_path = ndarray_type._get_serialization_path()
                    np = get_module(
                        "numpy",
                        required="Deserializing numpy columns requires numpy to be installed",
                    )
                    deserialized = np.load(
                        source_artifact.get_path(serialization_path["path"]).download()
                    )
                    np_deserialized_columns[
                        json_obj["columns"].index(col_name)
                    ] = deserialized[serialization_path["key"]]
                    ndarray_type._clear_serialization_path()

        for r_ndx, row in enumerate(json_obj["data"]):
            row_data = []
            for c_ndx, item in enumerate(row):
                cell = item
                if c_ndx in np_deserialized_columns:
                    cell = np_deserialized_columns[c_ndx][r_ndx]
                elif isinstance(item, dict) and "_type" in item:
                    obj = WBValue.init_from_json(item, source_artifact)
                    if obj is not None:
                        cell = obj
                row_data.append(cell)
            data.append(row_data)

        # construct Table with dtypes for each column if type information exists
        dtypes = None
        if column_types is not None:
            dtypes = [
                column_types.params["type_map"][col] for col in json_obj["columns"]
            ]

        new_obj = cls(columns=json_obj["columns"], data=data, dtype=dtypes)

        if column_types is not None:
            new_obj._column_types = column_types

        new_obj._update_keys()
        return new_obj

    def to_json(self, run_or_artifact):
        json_dict = super(Table, self).to_json(run_or_artifact)

        if isinstance(run_or_artifact, wandb.sdk.wandb_run.Run):
            json_dict.update(
                {
                    "_type": "table-file",
                    "ncols": len(self.columns),
                    "nrows": len(self.data),
                }
            )

        elif isinstance(run_or_artifact, wandb.sdk.wandb_artifacts.Artifact):
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
                # will not have the some cost as higher dimensional arrays
                is_1d_array = (
                    ndarray_type is not None
                    and "shape" in ndarray_type._params
                    and type(ndarray_type._params["shape"]) == list
                    and len(ndarray_type._params["shape"]) == 1
                    and ndarray_type._params["shape"][0]
                    <= self._MAX_EMBEDDING_DIMENSIONS
                )
                if is_1d_array:
                    self._column_types.params["type_map"][col_name] = _dtypes.ListType(
                        _dtypes.NumberType, ndarray_type._params["shape"][0]
                    )
                elif ndarray_type is not None:
                    np = get_module(
                        "numpy",
                        required="Serializing numpy requires numpy to be installed",
                    )
                    file_name = "{}_{}.npz".format(str(col_name), str(generate_id()))
                    npz_file_name = os.path.join(self._MEDIA_TMP.name, file_name)
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
                }
            )
        else:
            raise ValueError("to_json accepts wandb_run.Run or wandb_artifact.Artifact")

        return json_dict

    def iterrows(self):
        """Iterate over rows as (ndx, row)
        Yields
        ------
        index : int
            The index of the row. Using this value in other WandB tables
            will automatically build a relationship between the tables
        row : List[any]
            The data of the row
        """
        for ndx in range(len(self.data)):
            index = _TableIndex(ndx)
            index.set_table(self)
            yield index, self.data[ndx]

    def set_pk(self, col_name):
        # TODO: Docs
        assert col_name in self.columns
        self.cast(col_name, _PrimaryKeyType())

    def set_fk(self, col_name, table, table_col):
        # TODO: Docs
        assert col_name in self.columns
        assert col_name != self._pk_col
        self.cast(col_name, _ForeignKeyType(table, table_col))

    def _update_keys(self, force_last=False):
        """Updates the known key-like columns based on the current
        column types. If the state has been updated since
        the last update, we wrap the data appropriately in the Key classes

        Arguments:
        force_last: (bool) Determines wrapping the last column of data even if
        there are no key updates.
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
                    "Cannot unset primary key (column {})".format(self._pk_col)
                )
            # If there is a removed FK
            if len(self._fk_cols - _fk_cols) > 0:
                raise AssertionError(
                    "Cannot unset foreign key. Attempted to unset ({})".format(
                        self._fk_cols - _fk_cols
                    )
                )

            self._pk_col = _pk_col
            self._fk_cols = _fk_cols

        # Apply updates to data only if there are update or the caller
        # requested the final row to be updated
        if has_update or force_last:
            self._apply_key_updates(not has_update)

    def _apply_key_updates(self, only_last=False):
        """Appropriately wraps the underlying data in special key classes.

        Arguments:
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

    def add_column(self, name, data, optional=False):
        """Add a column of data to the table.

        Arguments
            name: (str) - the unique name of the column
            data: (list | np.array) - a column of homogenous data
            optional: (bool) - if null-like values are permitted
        """
        assert isinstance(name, str) and name not in self.columns
        is_np = is_numpy_array(data)
        assert isinstance(data, list) or is_np
        assert isinstance(optional, bool)
        is_first_col = len(self.columns) == 0
        assert is_first_col or len(data) == len(
            self.data
        ), "Expected length {}, found {}".format(len(self.data), len(data))

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
        except TypeError as err:
            # Undo the changes
            if is_first_col:
                self.data = []
                self.columns = []
            else:
                for ndx in range(len(self.data)):
                    self.data[ndx] = self.data[ndx][:-1]
                self.columns = self.columns[:-1]
            raise err

    def get_column(self, name, convert_to=None):
        """Retrieves a column of data from the table

        Arguments
            name: (str) - the name of the column
            convert_to: (str, optional)
                - "numpy": will convert the underlying data to numpy object
        """
        assert name in self.columns
        assert convert_to is None or convert_to == "numpy"
        if convert_to == "numpy":
            np = get_module(
                "numpy", required="Converting to numpy requires installing numpy"
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
        """Returns an array of row indexes which can be used in other tables to create links"""
        ndxs = []
        for ndx in range(len(self.data)):
            index = _TableIndex(ndx)
            index.set_table(self)
            ndxs.append(index)
        return ndxs

    def index_ref(self, index):
        """Get a reference to a particular row index in the table"""
        assert index < len(self.data)
        _index = _TableIndex(index)
        _index.set_table(self)
        return _index

    def add_computed_columns(self, fn):
        """Adds one or more computed columns based on existing data

        Args:
            fn: A function which accepts one or two parameters, ndx (int) and row (dict),
                which is expected to return a dict representing new columns for that row, keyed
                by the new column names.

                `ndx` is an integer representing the index of the row. Only included if `include_ndx`
                      is set to `True`.

                `row` is a dictionary keyed by existing columns
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
        res = super(_ForeignIndexType, self).to_json(artifact)
        if artifact is not None:
            table_name = "media/tables/t_{}".format(generate_id())
            entry = artifact.add(self.params["table"], table_name)
            res["params"]["table"] = entry.path
        else:
            raise AssertionError(
                "_ForeignIndexType does not support serialization without an artifact"
            )
        return res

    @classmethod
    def from_json(
        cls, json_dict, artifact,
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
        res = super(_ForeignKeyType, self).to_json(artifact)
        if artifact is not None:
            table_name = "media/tables/t_{}".format(generate_id())
            entry = artifact.add(self.params["table"], table_name)
            res["params"]["table"] = entry.path
        else:
            raise AssertionError(
                "_ForeignKeyType does not support serialization without an artifact"
            )
        return res

    @classmethod
    def from_json(
        cls, json_dict, artifact,
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


_dtypes.TypeRegistry.add(_ForeignIndexType)
_dtypes.TypeRegistry.add(_ForeignKeyType)
_dtypes.TypeRegistry.add(_PrimaryKeyType)
_dtypes.TypeRegistry.add(_TableType)
