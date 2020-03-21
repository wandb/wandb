# -*- coding: utf-8 -*-
"""History - Time series for Runs.

Track history from Run.log() calls.

"""


class History(object):
    """Time series data for Runs.
    """
    def __init__(self):
        self._step = 0
        self._data = dict()
        self._callback = None

    def _set_callback(self, cb):
        self._callback = cb

    def _row_update(self, row):
        self._data.update(row)

    def _row_add(self, row):
        self._data["_step"] = self._step
        self._step += 1
        self._data.update(row)
        if self._callback:
            self._callback(row=self._data)
        self._data = dict()
