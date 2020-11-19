#
# -*- coding: utf-8 -*-
"""
History tracks logged data over time. To use history from your script, call
wandb.log({"key": value}) at a single time step or multiple times in your
training loop. This generates a time series of saved scalars or media that is
saved to history.

In the UI, if you log a scalar at multiple timesteps W&B will render these
history metrics as line plots by default. If you log a single value in history,
compare across runs with a bar chart.

It's often useful to track a full time series as well as a single summary value.
For example, accuracy at every step in History and best accuracy in Summary.
By default, Summary is set to the final value of History.
"""

import time

from wandb.wandb_torch import TorchHistory


class History(object):
    """Time series data for Runs. This is essentially a list of dicts where each
        dict is a set of summary statistics logged.
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
