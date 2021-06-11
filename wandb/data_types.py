"""
Wandb has special data types for logging rich visualizations.

All of the special data types are subclasses of WBValue. All of the data types
serialize to JSON, since that is what wandb uses to save the objects locally
and upload them to the W&B server.
"""

from __future__ import print_function

import base64
import binascii
import codecs
import hashlib
import json
import logging
import os
import pprint
import re
import sys
import warnings

import six
import wandb
from wandb import util
from wandb.compat import tempfile

_PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6

if _PY3:
    from wandb.sdk.interface import _dtypes
    from wandb.sdk.data_types import (
        WBValue,
        Histogram,
        Media,
        BatchableMedia,
        Object3D,
        Molecule,
        Html,
        Video,
        ImageMask,
        BoundingBoxes2D,
        Classes,
        Image,
        Plotly,
        history_dict_to_json,
        val_to_json,
        _numpy_arrays_to_lists,
    )
else:
    from wandb.sdk_py27.interface import _dtypes
    from wandb.sdk_py27.data_types import (
        WBValue,
        Histogram,
        Media,
        BatchableMedia,
        Object3D,
        Molecule,
        Html,
        Video,
        ImageMask,
        BoundingBoxes2D,
        Classes,
        Image,
        Plotly,
        history_dict_to_json,
        val_to_json,
        _numpy_arrays_to_lists,
    )

__all__ = [
    "Audio",
    "Histogram",
    "Object3D",
    "Molecule",
    "Html",
    "Video",
    "ImageMask",
    "BoundingBoxes2D",
    "Classes",
    "Image",
    "Plotly",
    "history_dict_to_json",
    "val_to_json",
]


# Get rid of cleanup warnings in Python 2.7.
warnings.filterwarnings(
    "ignore", "Implicitly cleaning up", RuntimeWarning, "wandb.compat.tempfile"
)

# Staging directory so we can encode raw data into files, then hash them before
# we put them into the Run directory to be uploaded.
MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")


class _TableLinkMixin(object):
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


def _json_helper(val, artifact):
    if isinstance(val, WBValue):
        return val.to_json(artifact)
    elif val.__class__ == dict:
        res = {}
        for key in val:
            res[key] = _json_helper(val[key], artifact)
        return res
    elif hasattr(val, "tolist"):
        return util.json_friendly(val.tolist())[0]
    else:
        return util.json_friendly(val)[0]


class Table(Media):
    """The Table class is used to display and analyze tabular data.

    This class is the primary class used to generate the Table Visualizer
    in the UI: https://docs.wandb.ai/guides/data-vis/tables.

    Tables can be constructed with initial data using the `data` or
    `dataframe` parameters. Additionally, users can add data to Tables
    incrementally by using the `add_data`, `add_column`, and
    `add_computed_column` functions for adding rows, columns, and computed
    columns, respectively.

    Tables can be logged directly to runs using `run.log({"my_table": table})`
    or added to artifacts using `artifact.add(table, "my_table")`. Tables added
    directly to runs will produce a corresponding Table Visualizer in the
    Workspace which can be used for further analysis and exporting to reports.
    Tables added to artifacts can be viewed in the Artifact Tab and will render
    an equivalent Table Visualizer directly in the artifact browser.

    Note that Tables support numerous types of data: traditional scalar values,
    numpy arrays, and most subclasses of wandb.data_types.Media. This means you
    can embed Images, Video, Audio, and other sorts of rich, annotated media
    directly in Tables, alongside other traditional scalar values. Tables expect
    each value for a column to be of the same type. By default, a column supports
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

    @staticmethod
    def _assert_valid_columns(columns):
        valid_col_types = [str, int]
        if sys.version_info.major < 3:
            valid_col_types.append(unicode)  # noqa: F821 (unicode is in py2)
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
        assert util.is_numpy_array(
            ndarray
        ), "ndarray argument expects a `numpy.ndarray` object"
        self.data = []
        self._assert_valid_columns(columns)
        self.columns = columns
        self._make_column_types(dtype, optional)
        for row in ndarray:
            self.add_data(*row)

    def _init_from_dataframe(self, dataframe, columns, optional=True, dtype=None):
        assert util.is_pandas_data_frame(
            dataframe
        ), "dataframe argument expects a `pandas.core.frame.DataFrame` object"
        self.data = []
        self.columns = list(dataframe.columns)
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
                    if util.is_numpy_array(_eq):
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

    def _to_table_json(self, max_rows=None):
        # separate this method for easier testing
        if max_rows is None:
            max_rows = Table.MAX_ROWS
        if len(self.data) > max_rows:
            logging.warning("Truncating wandb.Table object to %i rows." % max_rows)
        return {"columns": self.columns, "data": self.data[:max_rows]}

    def bind_to_run(self, *args, **kwargs):
        data = self._to_table_json()
        tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ".table.json")
        data = _numpy_arrays_to_lists(data)
        util.json_dump_safer(data, codecs.open(tmp_path, "w", encoding="utf-8"))
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
                    np = util.get_module(
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

        new_obj = cls(columns=json_obj["columns"], data=data)

        if column_types is not None:
            new_obj._column_types = column_types

        new_obj._update_keys()
        return new_obj

    def to_json(self, run_or_artifact):
        json_dict = super(Table, self).to_json(run_or_artifact)

        if isinstance(run_or_artifact, wandb.wandb_sdk.wandb_run.Run):
            json_dict.update(
                {
                    "_type": "table-file",
                    "ncols": len(self.columns),
                    "nrows": len(self.data),
                }
            )

        elif isinstance(run_or_artifact, wandb.wandb_sdk.wandb_artifacts.Artifact):
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
                if ndarray_type is not None:
                    np = util.get_module(
                        "numpy",
                        required="Serializing numpy requires numpy to be installed",
                    )
                    file_name = "{}_{}.npz".format(
                        str(col_name), str(util.generate_id())
                    )
                    npz_file_name = os.path.join(MEDIA_TMP.name, file_name)
                    np.savez_compressed(
                        npz_file_name,
                        **{str(col_name): self.get_column(col_name, convert_to="numpy")}
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
        is_np = util.is_numpy_array(data)
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
            np = util.get_module(
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
            fn (function): A function which accepts one or two paramters: ndx (int) and row (dict)
                which is expected to return a dict representing new columns for that row, keyed
                by the new column names.
                    - `ndx` is an integer representing the index of the row. Only included if `include_ndx`
                        is set to true
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
    """Helper class for PartitionTable to track its parts
    """

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
    """ PartitionedTable represents a table which is composed
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
        if isinstance(artifact_or_run, wandb.wandb_sdk.wandb_run.Run):
            artifact_entry = self._get_artifact_reference_entry()
            if artifact_entry is None:
                raise ValueError(
                    "PartitionedTables must first be added to an Artifact before logging to a Run"
                )
            json_obj["artifact_path"] = artifact_entry.ref_url()
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


class Audio(BatchableMedia):
    """
    Wandb class for audio clips.

    Arguments:
        data_or_path: (string or numpy array) A path to an audio file
            or a numpy array of audio data.
        sample_rate: (int) Sample rate, required when passing in raw
            numpy array of audio data.
        caption: (string) Caption to display with audio.
    """

    _log_type = "audio-file"

    def __init__(self, data_or_path, sample_rate=None, caption=None):
        """Accepts a path to an audio file or a numpy array of audio data."""
        super(Audio, self).__init__()
        self._duration = None
        self._sample_rate = sample_rate
        self._caption = caption

        if isinstance(data_or_path, six.string_types):
            if Audio.path_is_reference(data_or_path):
                self._path = data_or_path
                self._sha256 = hashlib.sha256(data_or_path.encode("utf-8")).hexdigest()
                self._is_tmp = False
            else:
                self._set_file(data_or_path, is_tmp=False)
        else:
            if sample_rate is None:
                raise ValueError(
                    'Argument "sample_rate" is required when instantiating wandb.Audio with raw data.'
                )

            soundfile = util.get_module(
                "soundfile",
                required='Raw audio requires the soundfile package. To get it, run "pip install soundfile"',
            )

            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ".wav")
            soundfile.write(tmp_path, data_or_path, sample_rate)
            self._duration = len(data_or_path) / float(sample_rate)

            self._set_file(tmp_path, is_tmp=True)

    @classmethod
    def path_is_reference(cls, path):
        return bool(re.match(r"^(gs|s3|https?)://", path))

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "audio")

    @classmethod
    def from_json(cls, json_obj, source_artifact):
        return cls(
            source_artifact.get_path(json_obj["path"]).download(),
            caption=json_obj["caption"],
        )

    def bind_to_run(self, run, key, step, id_=None):
        if Audio.path_is_reference(self._path):
            raise ValueError(
                "Audio media created by a reference to external storage cannot currently be added to a run"
            )

        return super(Audio, self).bind_to_run(run, key, step, id_)

    def to_json(self, run):
        json_dict = super(Audio, self).to_json(run)
        json_dict.update(
            {"_type": self._log_type, "caption": self._caption,}
        )
        return json_dict

    @classmethod
    def seq_to_json(cls, seq, run, key, step):
        audio_list = list(seq)

        util.get_module(
            "soundfile",
            required="wandb.Audio requires the soundfile package. To get it, run: pip install soundfile",
        )
        base_path = os.path.join(run.dir, "media", "audio")
        util.mkdir_exists_ok(base_path)
        meta = {
            "_type": "audio",
            "count": len(audio_list),
            "audio": [a.to_json(run) for a in audio_list],
        }
        sample_rates = cls.sample_rates(audio_list)
        if sample_rates:
            meta["sampleRates"] = sample_rates
        durations = cls.durations(audio_list)
        if durations:
            meta["durations"] = durations
        captions = cls.captions(audio_list)
        if captions:
            meta["captions"] = captions

        return meta

    @classmethod
    def durations(cls, audio_list):
        return [a._duration for a in audio_list]

    @classmethod
    def sample_rates(cls, audio_list):
        return [a._sample_rate for a in audio_list]

    @classmethod
    def captions(cls, audio_list):
        captions = [a._caption for a in audio_list]
        if all(c is None for c in captions):
            return False
        else:
            return ["" if c is None else c for c in captions]

    def resolve_ref(self):
        if Audio.path_is_reference(self._path):
            # this object was already created using a ref:
            return self._path
        source_artifact = self._artifact_source.artifact

        resolved_name = source_artifact._local_path_to_name(self._path)
        if resolved_name is not None:
            target_entry = source_artifact.manifest.get_entry_by_path(resolved_name)
            if target_entry is not None:
                return target_entry.ref

        return None

    def __eq__(self, other):
        if Audio.path_is_reference(self._path) or Audio.path_is_reference(other._path):
            # one or more of these objects is an unresolved reference -- we'll compare
            # their reference paths instead of their SHAs:
            return (
                self.resolve_ref() == other.resolve_ref()
                and self._caption == other._caption
            )

        return super(Audio, self).__eq__(other) and self._caption == other._caption

    def __ne__(self, other):
        return not self.__eq__(other)


def is_numpy_array(data):
    np = util.get_module(
        "numpy", required="Logging raw point cloud data requires numpy"
    )
    return isinstance(data, np.ndarray)


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

        return cls(t1, t2, json_obj["join_key"],)

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
        if isinstance(artifact_or_run, wandb.wandb_sdk.wandb_run.Run):
            artifact_entry = self._get_artifact_reference_entry()
            if artifact_entry is None:
                raise ValueError(
                    "JoinedTables must first be added to an Artifact before logging to a Run"
                )
            json_obj["artifact_path"] = artifact_entry.ref_url()
        else:
            table1 = self._ensure_table_in_artifact(self._table1, artifact_or_run, 1)
            table2 = self._ensure_table_in_artifact(self._table2, artifact_or_run, 2)
            json_obj.update(
                {"table1": table1, "table2": table2, "join_key": self._join_key,}
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


class Bokeh(Media):
    """
    Wandb class for Bokeh plots.

    Arguments:
        val: Bokeh plot
    """

    _log_type = "bokeh-file"

    def __init__(self, data_or_path):
        super(Bokeh, self).__init__()
        bokeh = util.get_module("bokeh", required=True)
        if isinstance(data_or_path, str) and os.path.exists(data_or_path):
            with open(data_or_path, "r") as file:
                b_json = json.load(file)
            self.b_obj = bokeh.document.Document.from_json(b_json)
            self._set_file(data_or_path, is_tmp=False, extension=".bokeh.json")
        elif isinstance(data_or_path, bokeh.model.Model):
            _data = bokeh.document.Document()
            _data.add_root(data_or_path)
            # serialize/deserialize pairing followed by sorting attributes ensures
            # that the file's shas are equivalent in subsequent calls
            self.b_obj = bokeh.document.Document.from_json(_data.to_json())
            b_json = self.b_obj.to_json()
            if "references" in b_json["roots"]:
                b_json["roots"]["references"].sort(key=lambda x: x["id"])

            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ".bokeh.json")
            util.json_dump_safer(b_json, codecs.open(tmp_path, "w", encoding="utf-8"))
            self._set_file(tmp_path, is_tmp=True, extension=".bokeh.json")
        elif not isinstance(data_or_path, bokeh.document.Document):
            raise TypeError(
                "Bokeh constructor accepts Bokeh document/model or path to Bokeh json file"
            )

    def get_media_subdir(self):
        return os.path.join("media", "bokeh")

    def to_json(self, run):
        # TODO: (tss) this is getting redundant for all the media objects. We can probably
        # pull this into Media#to_json and remove this type override for all the media types.
        # There are only a few cases where the type is different between artifacts and runs.
        json_dict = super(Bokeh, self).to_json(run)
        json_dict["_type"] = self._log_type
        return json_dict

    @classmethod
    def from_json(cls, json_obj, source_artifact):
        return cls(source_artifact.get_path(json_obj["path"]).download())


def _nest(thing):
    # Use tensorflows nest function if available, otherwise just wrap object in an array"""

    tfutil = util.get_module("tensorflow.python.util")
    if tfutil:
        return tfutil.nest.flatten(thing)
    else:
        return [thing]


class Graph(Media):
    """Wandb class for graphs

    This class is typically used for saving and diplaying neural net models.  It
    represents the graph as an array of nodes and edges.  The nodes can have
    labels that can be visualized by wandb.

    Examples:
        Import a keras model:
        ```
            Graph.from_keras(keras_model)
        ```

    Attributes:
        format (string): Format to help wandb display the graph nicely.
        nodes ([wandb.Node]): List of wandb.Nodes
        nodes_by_id (dict): dict of ids -> nodes
        edges ([(wandb.Node, wandb.Node)]): List of pairs of nodes interpreted as edges
        loaded (boolean): Flag to tell whether the graph is completely loaded
        root (wandb.Node): root node of the graph
    """

    _log_type = "graph-file"

    def __init__(self, format="keras"):
        super(Graph, self).__init__()
        # LB: TODO: I think we should factor criterion and criterion_passed out
        self.format = format
        self.nodes = []
        self.nodes_by_id = {}
        self.edges = []
        self.loaded = False
        self.criterion = None
        self.criterion_passed = False
        self.root = None  # optional root Node if applicable

    def _to_graph_json(self, run=None):
        # Needs to be it's own function for tests
        return {
            "format": self.format,
            "nodes": [node.to_json() for node in self.nodes],
            "edges": [edge.to_json() for edge in self.edges],
        }

    def bind_to_run(self, *args, **kwargs):
        data = self._to_graph_json()
        tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ".graph.json")
        data = _numpy_arrays_to_lists(data)
        util.json_dump_safer(data, codecs.open(tmp_path, "w", encoding="utf-8"))
        self._set_file(tmp_path, is_tmp=True, extension=".graph.json")
        if self.is_bound():
            return
        super(Graph, self).bind_to_run(*args, **kwargs)

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "graph")

    def to_json(self, run):
        json_dict = super(Graph, self).to_json(run)
        json_dict["_type"] = self._log_type
        return json_dict

    def __getitem__(self, nid):
        return self.nodes_by_id[nid]

    def pprint(self):
        for edge in self.edges:
            pprint.pprint(edge.attributes)
        for node in self.nodes:
            pprint.pprint(node.attributes)

    def add_node(self, node=None, **node_kwargs):
        if node is None:
            node = Node(**node_kwargs)
        elif node_kwargs:
            raise ValueError(
                "Only pass one of either node ({node}) or other keyword arguments ({node_kwargs})".format(
                    node=node, node_kwargs=node_kwargs
                )
            )
        self.nodes.append(node)
        self.nodes_by_id[node.id] = node

        return node

    def add_edge(self, from_node, to_node):
        edge = Edge(from_node, to_node)
        self.edges.append(edge)

        return edge

    @classmethod
    def from_keras(cls, model):
        graph = cls()
        # Shamelessly copied (then modified) from keras/keras/utils/layer_utils.py
        sequential_like = cls._is_sequential(model)

        relevant_nodes = None
        if not sequential_like:
            relevant_nodes = []
            for v in model._nodes_by_depth.values():
                relevant_nodes += v

        layers = model.layers
        for i in range(len(layers)):
            node = Node.from_keras(layers[i])
            if hasattr(layers[i], "_inbound_nodes"):
                for in_node in layers[i]._inbound_nodes:
                    if relevant_nodes and in_node not in relevant_nodes:
                        # node is not part of the current network
                        continue
                    for in_layer in _nest(in_node.inbound_layers):
                        inbound_keras_node = Node.from_keras(in_layer)

                        if inbound_keras_node.id not in graph.nodes_by_id:
                            graph.add_node(inbound_keras_node)
                        inbound_node = graph.nodes_by_id[inbound_keras_node.id]

                        graph.add_edge(inbound_node, node)
            graph.add_node(node)
        return graph

    @classmethod
    def _is_sequential(cls, model):
        sequential_like = True

        if (
            model.__class__.__name__ != "Sequential"
            and hasattr(model, "_is_graph_network")
            and model._is_graph_network
        ):
            nodes_by_depth = model._nodes_by_depth.values()
            nodes = []
            for v in nodes_by_depth:
                # TensorFlow2 doesn't insure inbound is always a list
                inbound = v[0].inbound_layers
                if not hasattr(inbound, "__len__"):
                    inbound = [inbound]
                if (len(v) > 1) or (len(v) == 1 and len(inbound) > 1):
                    # if the model has multiple nodes
                    # or if the nodes have multiple inbound_layers
                    # the model is no longer sequential
                    sequential_like = False
                    break
                nodes += v
            if sequential_like:
                # search for shared layers
                for layer in model.layers:
                    flag = False
                    if hasattr(layer, "_inbound_nodes"):
                        for node in layer._inbound_nodes:
                            if node in nodes:
                                if flag:
                                    sequential_like = False
                                    break
                                else:
                                    flag = True
                    if not sequential_like:
                        break
        return sequential_like


class Node(WBValue):
    """
    Node used in `Graph`
    """

    def __init__(
        self,
        id=None,
        name=None,
        class_name=None,
        size=None,
        parameters=None,
        output_shape=None,
        is_output=None,
        num_parameters=None,
        node=None,
    ):
        self._attributes = {"name": None}
        self.in_edges = {}  # indexed by source node id
        self.out_edges = {}  # indexed by dest node id
        # optional object (eg. PyTorch Parameter or Module) that this Node represents
        self.obj = None

        if node is not None:
            self._attributes.update(node._attributes)
            del self._attributes["id"]
            self.obj = node.obj

        if id is not None:
            self.id = id
        if name is not None:
            self.name = name
        if class_name is not None:
            self.class_name = class_name
        if size is not None:
            self.size = size
        if parameters is not None:
            self.parameters = parameters
        if output_shape is not None:
            self.output_shape = output_shape
        if is_output is not None:
            self.is_output = is_output
        if num_parameters is not None:
            self.num_parameters = num_parameters

    def to_json(self, run=None):
        return self._attributes

    def __repr__(self):
        return repr(self._attributes)

    @property
    def id(self):
        """Must be unique in the graph"""
        return self._attributes.get("id")

    @id.setter
    def id(self, val):
        self._attributes["id"] = val
        return val

    @property
    def name(self):
        """Usually the type of layer or sublayer"""
        return self._attributes.get("name")

    @name.setter
    def name(self, val):
        self._attributes["name"] = val
        return val

    @property
    def class_name(self):
        """Usually the type of layer or sublayer"""
        return self._attributes.get("class_name")

    @class_name.setter
    def class_name(self, val):
        self._attributes["class_name"] = val
        return val

    @property
    def functions(self):
        return self._attributes.get("functions", [])

    @functions.setter
    def functions(self, val):
        self._attributes["functions"] = val
        return val

    @property
    def parameters(self):
        return self._attributes.get("parameters", [])

    @parameters.setter
    def parameters(self, val):
        self._attributes["parameters"] = val
        return val

    @property
    def size(self):
        return self._attributes.get("size")

    @size.setter
    def size(self, val):
        """Tensor size"""
        self._attributes["size"] = tuple(val)
        return val

    @property
    def output_shape(self):
        return self._attributes.get("output_shape")

    @output_shape.setter
    def output_shape(self, val):
        """Tensor output_shape"""
        self._attributes["output_shape"] = val
        return val

    @property
    def is_output(self):
        return self._attributes.get("is_output")

    @is_output.setter
    def is_output(self, val):
        """Tensor is_output"""
        self._attributes["is_output"] = val
        return val

    @property
    def num_parameters(self):
        return self._attributes.get("num_parameters")

    @num_parameters.setter
    def num_parameters(self, val):
        """Tensor num_parameters"""
        self._attributes["num_parameters"] = val
        return val

    @property
    def child_parameters(self):
        return self._attributes.get("child_parameters")

    @child_parameters.setter
    def child_parameters(self, val):
        """Tensor child_parameters"""
        self._attributes["child_parameters"] = val
        return val

    @property
    def is_constant(self):
        return self._attributes.get("is_constant")

    @is_constant.setter
    def is_constant(self, val):
        """Tensor is_constant"""
        self._attributes["is_constant"] = val
        return val

    @classmethod
    def from_keras(cls, layer):
        node = cls()

        try:
            output_shape = layer.output_shape
        except AttributeError:
            output_shape = ["multiple"]

        node.id = layer.name
        node.name = layer.name
        node.class_name = layer.__class__.__name__
        node.output_shape = output_shape
        node.num_parameters = layer.count_params()

        return node


class Edge(WBValue):
    """
    Edge used in `Graph`
    """

    def __init__(self, from_node, to_node):
        self._attributes = {}
        self.from_node = from_node
        self.to_node = to_node

    def __repr__(self):
        temp_attr = dict(self._attributes)
        del temp_attr["from_node"]
        del temp_attr["to_node"]
        temp_attr["from_id"] = self.from_node.id
        temp_attr["to_id"] = self.to_node.id
        return str(temp_attr)

    def to_json(self, run=None):
        return [self.from_node.id, self.to_node.id]

    @property
    def name(self):
        """Optional, not necessarily unique"""
        return self._attributes.get("name")

    @name.setter
    def name(self, val):
        self._attributes["name"] = val
        return val

    @property
    def from_node(self):
        return self._attributes.get("from_node")

    @from_node.setter
    def from_node(self, val):
        self._attributes["from_node"] = val
        return val

    @property
    def to_node(self):
        return self._attributes.get("to_node")

    @to_node.setter
    def to_node(self, val):
        self._attributes["to_node"] = val
        return val


# Custom dtypes for typing system


class _ImageFileType(_dtypes.Type):
    name = "image-file"
    legacy_names = ["wandb.Image"]
    types = [Image]

    def __init__(self, box_keys=None, mask_keys=None):
        if box_keys is None:
            box_keys = _dtypes.UnknownType()
        elif isinstance(box_keys, _dtypes.ConstType):
            box_keys = box_keys
        elif not isinstance(box_keys, list):
            raise TypeError("box_keys must be a list")
        else:
            box_keys = _dtypes.ConstType(set(box_keys))

        if mask_keys is None:
            mask_keys = _dtypes.UnknownType()
        elif isinstance(mask_keys, _dtypes.ConstType):
            mask_keys = mask_keys
        elif not isinstance(mask_keys, list):
            raise TypeError("mask_keys must be a list")
        else:
            mask_keys = _dtypes.ConstType(set(mask_keys))

        self.params.update(
            {"box_keys": box_keys, "mask_keys": mask_keys,}
        )

    def assign_type(self, wb_type=None):
        if isinstance(wb_type, _ImageFileType):
            box_keys = self.params["box_keys"].assign_type(wb_type.params["box_keys"])
            mask_keys = self.params["mask_keys"].assign_type(
                wb_type.params["mask_keys"]
            )
            if not (
                isinstance(box_keys, _dtypes.InvalidType)
                or isinstance(mask_keys, _dtypes.InvalidType)
            ):
                return _ImageFileType(box_keys, mask_keys)

        return _dtypes.InvalidType()

    @classmethod
    def from_obj(cls, py_obj):
        if not isinstance(py_obj, Image):
            raise TypeError("py_obj must be a wandb.Image")
        else:
            if hasattr(py_obj, "_boxes") and py_obj._boxes:
                box_keys = list(py_obj._boxes.keys())
            else:
                box_keys = []

            if hasattr(py_obj, "masks") and py_obj.masks:
                mask_keys = list(py_obj.masks.keys())
            else:
                mask_keys = []

            return cls(box_keys, mask_keys)


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
            table_name = "media/tables/t_{}".format(util.generate_id())
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
            table_name = "media/tables/t_{}".format(util.generate_id())
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


class _AudioFileType(_dtypes.Type):
    name = "audio-file"
    types = [Audio]


class _BokehFileType(_dtypes.Type):
    name = "bokeh-file"
    types = [Bokeh]


class _JoinedTableType(_dtypes.Type):
    name = "joined-table"
    types = [JoinedTable]


class _PartitionedTableType(_dtypes.Type):
    name = "partitioned-table"
    types = [PartitionedTable]


_dtypes.TypeRegistry.add(_AudioFileType)
_dtypes.TypeRegistry.add(_BokehFileType)
_dtypes.TypeRegistry.add(_ImageFileType)
_dtypes.TypeRegistry.add(_TableType)
_dtypes.TypeRegistry.add(_JoinedTableType)
_dtypes.TypeRegistry.add(_PartitionedTableType)
_dtypes.TypeRegistry.add(_ForeignKeyType)
_dtypes.TypeRegistry.add(_PrimaryKeyType)
_dtypes.TypeRegistry.add(_ForeignIndexType)
