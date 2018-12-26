import collections
import sys

import wandb

TYPE_TO_TYPESTRING = {
    str: 'str',
    int: 'int',
    float: 'float',
    wandb.types.Image: 'image',
    wandb.types.Percentage: 'percentage',
    wandb.types.Histogram: 'histogram'

}

# Just used in an error message
VALID_TYPE_NAMES = [
    t.__name__ if t.__module__ == 'builtins' else '{}.{}'.format(
        t.__module__, t.__name__)
    for t in TYPE_TO_TYPESTRING.keys()]


class TypedTable(object):
    """A table of typed data.

    A set of rows, which are dicts that share the same key set. The type
    must be the same for a given key across rows. The type for each
    key must be set by calling set_columns() before adding any rows.
    """

    def __init__(self, output):
        # Object that we can call add(row) on.
        self._output = output
        self._types = {}
        self._count = 0

    def set_columns(self, types):
        """Set the column types

        args:
            types: iterable of (column_name, type) pairs.
        """
        if self._types:
            raise wandb.Error('TypedTable.set_columns called more than once.')
        try:
            for key, type_ in types:
                if type_ not in TYPE_TO_TYPESTRING:
                    raise wandb.Error('TypedTable.set_columns received invalid type ({}) for key "{}".\n  Valid types: {}'.format(
                        type_, key, '[%s]' % ', '.join(VALID_TYPE_NAMES)))
        except TypeError:
            raise wandb.Error(
                'TypedTable.set_columns requires iterable of (column_name, type) pairs.')
        self._types = dict(types)
        self._output.add({
            'typemap': {k: TYPE_TO_TYPESTRING[type_] for k, type_ in types},
            'columns': [t[0] for t in types]})

    def add(self, row):
        """Add a row to the table.

        Args:
            row: A dict whose keys match the keys added in set_columns, and whose
                values can be cast to the types added in set_columns.
        """
        if not self._types:
            raise wandb.Error(
                'TypedTable.set_columns must be called before add.')
        mapped_row = {}
        for key, val in row.items():
            try:
                typed_val = self._types[key](val)
                if hasattr(typed_val, 'encode'):
                    typed_val = typed_val.encode()
                mapped_row[key] = typed_val
            except KeyError:
                raise wandb.Error(
                    'TypedTable.add received key ("%s") which wasn\'t provided to set_columns' % key)
            except:
                raise wandb.Error('TypedTable.add couldn\'t convert and encode ("{}") provided for key ("{}") to type ({})'.format(
                    val, key, self._types[key]))
        self._output.add(mapped_row)
        self._count += 1

    def count(self):
        return self._count
