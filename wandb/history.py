#!/usr/bin/env python

from __future__ import print_function

import collections
import contextlib
import copy
import numbers
import json
import os
import six
from threading import Lock
import time
import traceback
import warnings
import weakref

from wandb.wandb_torch import TorchHistory
import wandb
from wandb import util
from wandb import data_types


class History(object):
    """Time series data for Runs.

    See the documentation online: https://docs.wandb.com/docs/logs.html
    """

    def __init__(self, fname, out_dir='.', add_callback=None, stream_name="default"):
        self._start_time = wandb.START_TIME
        self.out_dir = out_dir
        self.fname = os.path.join(out_dir, fname)
        self.rows = []
        self.row = {}
        self.stream_name = stream_name
        # This enables / disables history logging. It's used by the
        # History.step() context manager to avoid compute-heavy computations
        # that are only necessary for logging.
        self.compute = True
        self.batched = False
        # not all rows have the same keys. this is the union of them all.
        self._keys = set()
        self._process = "user" if os.getenv("WANDB_INITED") else "wandb"
        self._streams = {}
        self._steps = 0  # index of the step to which we are currently logging
        self._lock = Lock()
        self._torch = None
        self.load()
        self._file = open(self.fname, 'a')
        self._add_callback = add_callback

    def load(self):
        self.rows = []
        try:
            # only preload the default stream, TODO: better stream support
            if self.stream_name == "default":
                with open(self.fname) as f:
                    for line in f:
                        try:
                            self._index(json.loads(line))
                        except TypeError:
                            print('warning: malformed history line: %s...' %
                                  line[:40])
                # initialize steps and run time based on existing data.
                if '_step' in self.row:
                    self._steps = self.row['_step'] + 1
                # fudge the start_time to compensate for previous run length
                if '_runtime' in self.row:
                    self._start_time = wandb.START_TIME - self.row['_runtime']
                self.row = {}
        except IOError:
            pass

    def keys(self):
        rich_keys = []
        if self.rows:
            rich_keys = [k for k, v in six.iteritems(
                self.rows[-1]) if isinstance(v, dict) and v.get("_type")]
        return [k for k in self._keys - set(rich_keys) if not k.startswith("_")]

    def stream(self, name):
        """Stream can be used to record different time series:

        run.history.stream("batch").add({"gradients": 1})
        """
        if self.stream_name != "default":
            raise ValueError("Nested streams aren't supported")
        if self._streams.get(name) == None:
            self._streams[name] = History(self.fname, out_dir=self.out_dir,
                                          add_callback=self._add_callback, stream_name=name)
        return self._streams[name]

    def column(self, key):
        """Iterator over a given column, skipping steps that don't have that key
        """
        for row in self.rows:
            if key in row:
                yield row[key]

    def add(self, row={}, step=None):
        """Adds or updates a history step.

        If row isn't specified, will write the current state of row.

        If step is specified, the row will be written only when add() is called with
        a different step value.

        run.history.row["duration"] = 1.0
        run.history.add({"loss": 1})
        => {"duration": 1.0, "loss": 1}

        """
        if not isinstance(row, collections.Mapping):
            raise wandb.Error('history.add expects dict-like object')

        if step is None:
            self.update(row)
            if not self.batched:
                self._write()
        else:
            if not isinstance(step, numbers.Integral):
                raise wandb.Error(
                    "Step must be an integer, not {}".format(step))
            elif step < self._steps:
                warnings.warn(
                    "Adding to old History rows isn't currently supported. Dropping.", wandb.WandbWarning)
                return
            elif step == self._steps:
                pass
            elif self.batched:
                raise wandb.Error(
                    "Can't log to a particular History step ({}) while in batched mode.".format(step))
            else:  # step > self._steps
                self._write()
                self._steps = step

            self.update(row)

    def update(self, new_vals):
        """Add a dictionary of values to the current step without writing it to disk.
        """
        for k, v in six.iteritems(new_vals):
            k = k.strip()
            if k in self.row:
                warnings.warn("Adding history key ({}) that is already set in this step".format(
                    k), wandb.WandbWarning)
            self.row[k] = v

    @contextlib.contextmanager
    def step(self, compute=True):
        """Context manager to gradually build a history row, then commit it at the end.

        To reduce the number of conditionals needed, code can check run.history.compute:

        with run.history.step(batch_idx % log_interval == 0):
            run.history.add({"nice": "ok"})
            if run.history.compute:
                # Something expensive here
        """
        if self.batched:  # we're already in a context manager
            raise wandb.Error("Nested History step contexts aren't supported")
        self.batched = True
        self.compute = compute
        yield self
        if compute:
            self._write()
        compute = True

    @property
    def torch(self):
        if self._torch is None:
            self._torch = TorchHistory(self)
        return self._torch

    def log_tf_summary(self, summary_pb_bin):
        from wandb.tensorflow import tf_summary_to_dict
        self.add(tf_summary_to_dict(summary_pb_bin))

    def _index(self, row):
        """Add a row to the internal list of rows without writing it to disk.

        This function should keep the data structure consistent so it's usable
        for both adding new rows, and loading pre-existing histories.
        """
        self.rows.append(row)
        self._keys.update(row.keys())
        self._steps += 1

    def _transform(self):
        """Transforms special classes into the proper format before writing"""
        self.row = data_types.to_json(self.row)

    def _write(self):
        if self.row:
            self._lock.acquire()
            try:
                self.row['_runtime'] = time.time() - self._start_time
                self.row['_timestamp'] = time.time()
                self.row['_step'] = self._steps
                if self.stream_name != "default":
                    self.row["_stream"] = self.stream_name
                self._transform()
                self._file.write(util.json_dumps_safer_history(self.row))
                self._file.write('\n')
                self._file.flush()
                self._index(self.row)
                if self._add_callback:
                    self._add_callback(self.row)
                self.row = {}
            finally:
                self._lock.release()
            return True
        else:
            return False

    def close(self):
        self._write()
        self._lock.acquire()
        try:
            if self._file:
                self._file.close()
                self._file = None
        finally:
            self._lock.release()
