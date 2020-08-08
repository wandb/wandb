# -*- coding: utf-8 -*-
"""History - Time series for Runs.

Track history from Run.log() calls.

"""

import time

from wandb.wandb_torch import TorchHistory


class History(object):
    """Time series data for Runs.
    """

    def __init__(self, run):
        self._run = run
        self._step = 0
        self._data = dict()
        self._callback = None
        self._torch = None
        self.compute = True

    def _set_callback(self, cb):
        self._callback = cb

    def _row_update(self, row):
        self._data.update(row)

    def _row_add(self, row):
        self._data.update(row)
        self._flush()
        self._step += 1

    def _update_step(self):
        """Called after receiving the run from the internal process"""
        self._step = self._run.starting_step

    def _flush(self):
        if len(self._data) > 0:
            self._data["_step"] = self._step
            self._data["_runtime"] = int(
                self._data.get("_runtime", time.time() - self.start_time)
            )
            self._data["_timestamp"] = int(self._data.get("_timestamp", time.time()))
            if self._callback:
                self._callback(row=self._data, step=self._step)
            self._data = dict()

    @property
    def start_time(self):
        return self._run.start_time

    def add(self, d):
        self._row_add(d)

    @property
    def torch(self):
        if self._torch is None:
            self._torch = TorchHistory(self)
        return self._torch
