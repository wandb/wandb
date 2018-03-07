#!/usr/bin/env python

from __future__ import print_function

import collections
import contextlib
import copy
import json
import os
import time
from threading import Lock
import warnings
import weakref
import six

from wandb.wandb_torch import TorchHistory
import wandb
from wandb import util
from wandb import media


class History(object):
    """Used to store data that changes over time during runs. """

    def __init__(self, fname, out_dir='.', add_callback=None, stream_name="default"):
        self._start_time = wandb.START_TIME
        self.out_dir = out_dir
        self.fname = os.path.join(out_dir, fname)
        self.rows = []
        self.row = {}
        self.stream_name = stream_name
        # during a batched context logging may still be disabled. we do it this way
        # so people don't have to litter their code with conditionals
        self.compute = False
        self.batched = False
        # not all rows have the same keys. this is the union of them all.
        self._keys = set()
        self._streams = {}
        self._steps = 0
        self._lock = Lock()
        self._torch = None
        try:
            # only preload the default stream, TODO: better stream support
            if stream_name == "default":
                with open(self.fname) as f:
                    for line in f:
                        self._index(json.loads(line))
        except IOError:
            pass

        self._file = open(self.fname, 'a')
        self._add_callback = add_callback

    def keys(self):
        return list(self._keys)

    def stream(self, name):
        """stream can be used to record different time series:

        run.history.stream("batch").add({"gradients": 1})
        """
        if self.stream_name != "default":
            raise ValueError("Nested streams aren't supported")
        if self._streams.get(name) == None:
            self._streams[name] = History(self.fname, out_dir=self.out_dir,
                                          add_callback=self._add_callback, stream_name=name)
        return self._streams[name]

    def column(self, key):
        """Iterator over a given column, skipping rows that don't have a key
        """
        for row in self.rows:
            if key in row:
                yield row[key]

    def add(self, row={}):
        """Adds keys to history and writes the row.  If row isn't specified, will write
        the current state of row.

        run.history.row["duration"] = 1.0
        run.history.add({"loss": 1})
        => {"duration": 1.0, "loss": 1}

        """
        if not isinstance(row, collections.Mapping):
            raise wandb.Error('history.add expects dict-like object')
        self.row.update(row)
        if not self.batched:
            self._write()

    @contextlib.contextmanager
    def step(self, compute=True):
        """Context manager to gradually build a history row, then commit it at the end.

        To reduce the number of conditionals needed, code can check run.history.compute:

        with run.history.step(batch_idx % log_interval == 0):
            run.history.add({"nice": "ok"})
            if run.history.compute:
                # Something expensive here
        """
        self.row = {}
        self.batched = True
        self.compute = compute
        yield self
        if compute:
            self._write()

    @property
    def torch(self):
        if self._torch is None:
            self._torch = TorchHistory(self)
        return self._torch

    def _index(self, row):
        """Internal row adding method that updates step, and keys"""
        # TODO: store a downsampled representation in memory
        self.rows.append(row)
        self._keys.update(row.keys())
        self._steps += 1

    def _transform(self):
        """Transforms media classes into the proper format before writing"""
        for key, val in six.iteritems(self.row):
            if type(val) in (list, tuple) and len(val) > 0:
                is_image = [isinstance(v, media.Image) for v in val]
                if all(is_image):
                    self.row[key] = media.Image.transform(val, self.out_dir,
                                                          "{}_{}.jpg".format(key, self.row["_step"]))
                elif any(is_image):
                    raise ValueError(
                        "Mixed media types in the same list aren't supported")

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
                self._file.write(util.json_dumps_safer(self.row))
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
            self._file.close()
            self._file = None
        finally:
            self._lock.release()
