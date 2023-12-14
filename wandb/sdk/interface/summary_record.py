"""Summary Record.

This module implements a summary record as an intermediate format before being converted
to a protocol buffer.
"""

import typing as t


class SummaryRecord:
    """Encodes a diff -- analogous to the SummaryRecord protobuf message."""

    update: t.List["SummaryItem"]
    remove: t.List["SummaryItem"]

    def __init__(self):
        self.update = []
        self.remove = []

    def __str__(self):
        s = "SummaryRecord:\n  Update:\n    "
        s += "\n    ".join([str(item) for item in self.update])
        s += "\n  Remove:\n    "
        s += "\n    ".join([str(item) for item in self.remove])
        s += "\n"
        return s

    __repr__ = __str__

    def _add_next_parent(self, parent_key):
        with_next_parent = SummaryRecord()
        with_next_parent.update = [
            item._add_next_parent(parent_key) for item in self.update
        ]
        with_next_parent.remove = [
            item._add_next_parent(parent_key) for item in self.remove
        ]

        return with_next_parent


class SummaryItem:
    """Analogous to the SummaryItem protobuf message."""

    key: t.Tuple[str]
    value: t.Any

    def __init__(self):
        self.key = tuple()
        self.value = None

    def __str__(self):
        return "SummaryItem: key: " + str(self.key) + " value: " + str(self.value)

    __repr__ = __str__

    def _add_next_parent(self, parent_key):
        with_next_parent = SummaryItem()

        key = self.key
        if not isinstance(key, tuple):
            key = (key,)

        with_next_parent.key = (parent_key,) + self.key
        with_next_parent.value = self.value

        return with_next_parent
