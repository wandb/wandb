import collections
import sys

import wandb

TYPE_TO_TYPESTRING = {
    str: 'str',
    int: 'int',
    float: 'float',
    wandb.types.Image: 'image'
}

# Just used in an error message
VALID_TYPE_NAMES = [
    t.__name__ if t.__module__ == 'builtins' else '%s.%s' % (
        t.__module__, t.__name__)
    for t in TYPE_TO_TYPESTRING.keys()]


class TypedTable(object):
    """A table of typed data.

    A set of rows, which are dicts that share the same key set. The type
    must be the same for a given key across rows. The type for each
    key must be set by calling setup() before adding any rows.
    """

    def __init__(self, output):
        # Object that we can call add(row) on.
        self._output = output
        self._types = {}
        self._count = 0

    def setup(self, types):
        """Set the column types

        args:
            types: dict mapping from column name to type.
        """
        if self._types:
            raise wandb.Error('TypedTable.setup called more than once.')
        if not isinstance(types, collections.Mapping):
            raise wandb.Error('TypedTable.setup expected dict-like object.')
        for key, type_ in types.items():
            if type_ not in TYPE_TO_TYPESTRING:
                raise wandb.Error('TypedTable.setup received invalid type (%s) for key "%s".\n  Valid types: %s' % (
                    type_, key, '[%s]' % ', '.join(VALID_TYPE_NAMES)))
        self._types = types
        self._output.add(
            {k: TYPE_TO_TYPESTRING[type_] for k, type_ in types.items()})

    def add(self, row):
        """Add a row to the table.

        Args:
            row: A dict whose keys match the keys added in setup, and whose
                values can be cast to the types added in setup.
        """
        if not self._types:
            raise wandb.Error('TypedTable.setup must be called before add.')
        mapped_row = {}
        for key, val in row.items():
            try:
                typed_val = self._types[key](val)
                if hasattr(typed_val, 'encode'):
                    typed_val = typed_val.encode()
                mapped_row[key] = typed_val
            except KeyError:
                raise wandb.Error(
                    'TypedTable.add received key ("%s") which wasn\'t provided to setup')
            except:
                raise wandb.Error('TypedTable.add couldn\'t convert and encode ("%s") provided for key ("%s") to type (%s)' % (
                    val, key, self._types[key]))
        self._output.add(mapped_row)
        self._count += 1

    def count(self):
        return self._count
