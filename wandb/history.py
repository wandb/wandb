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

torch = None  # dynamically imported by History.torch
import wandb
from wandb import util


class History(object):
    """Used to store data that changes over time during runs."""

    def __init__(self, fname, out_dir='.', add_callback=None):
        self._start_time = wandb.START_TIME

        # internal row used to accumulate data for build_row()
        self._accumulator = None

        # during a row-building context logging may still be disabled. we do it this way
        # so people don't have to litter their code with conditionals
        self._build_row_enabled = False

        # not all rows have the same keys. this is the union of them all.
        self._keys = set()

        self.fname = os.path.join(out_dir, fname)
        self.rows = []
        try:
            with open(self.fname) as f:
                for line in f:
                    self._add_row(json.loads(line))
        except IOError:
            pass

        self._file = open(self.fname, 'w')
        self._add_callback = add_callback
        self._torch = None

    @contextlib.contextmanager
    def build_row(self, enabled=True):
        """Context manager to gradually build a history row, then commit it at the end.

        Here's how you can use this to periodically log a neural net's parameters and
        gradients:

            for batch_idx, (data, target) in enumerate(train_loader):
                with run.history.build_row(batch_idx % log_interval == 0):
                    run.history.torch.log_stats(model)

                    optimizer.zero_grad()
                    output = model(data)
                    loss = F.nll_loss(output, target)
                    loss.backward()
                    optimizer.step()
        """
        self._accumulator = {}
        self._build_row_enabled = enabled
        yield
        accumulator = self._accumulator
        self._accumulator = None
        if enabled:
            self.add(accumulator)

    def _building_row(self):
        return self._accumulator is not None and self._build_row_enabled

    def update_row(self, d):
        """dict-like update method to make it convenient to add sets of things to a row
        that's being built.
        """
        if self._accumulator is None:
            raise wandb.Error("Can't call update_row() outside of a build_row() context.")
        elif self._build_row_enabled:
            self._accumulator.update(d)

    def __setitem__(self, key, value):
        if self._accumulator is None:
            raise wandb.Error("Can't set history items outside of a build_row() context.")
        elif self._build_row_enabled:
            self._accumulator[key] = value
        # TODO(adrian): return value here? should this behave like a dict?
        # we don't want to teach people to read data from this that won't
        # necessarily be computed when logging is disabled

    def keys(self):
        return list(self._keys)

    def column(self, key):
        """Fetches a key from all rows that have it. Skips those that don't.
        """
        for row in self.rows:
            if key in row:
                yield row[key]

    def add(self, row):
        if self._accumulator is not None:
            # TODO(adrian): should we actually prevent this? maybe it'd be better for this to call update_row()
            raise wandb.Error("Can't call history.add while building a row. Use .update_row() instead.")
        if not isinstance(row, collections.Mapping):
            raise wandb.Error('history.add expects dict-like object')

        row = copy.deepcopy(row)
        row['_runtime'] = time.time() - self._start_time
        self._file.write(util.json_dumps_safer(row))
        self._add_row(row)
        self._file.write('\n')
        self._file.flush()
        if self._add_callback:
            self._add_callback(row)

    def _add_row(self, row):
        """Internal row-adding method that doesn't write the row to a file
        """
        self.rows.append(row)
        self._keys.update(row.keys())

    @property
    def torch(self):
        if self._torch is None:
            global torch
            import torch
            self._torch = TorchHistory(self)
        return self._torch

    def close(self):
        self._file.close()
        self._file = None


class TorchHistory(object):
    """History methods specific to PyTorch
    """
    def __init__(self, history):
        self._history = weakref.ref(history)
        self._hook_handles = {}

    def log_stats(self, variable_or_module, name=None, prefix='_', values=True, gradients=True):
        """Log distribution statistics for a torch Variable or Module and its next
        gradient in History.

        For a Variable, logs statistics on its current data and gradient whenever
        its backward() method is next called. For a module, logs the same on all
        its Parameters (including those of submodules).

        Here's how you might use this function to instrument the hidden units of a
        network:

            def forward(self, x):
                x = F.relu(F.max_pool2d(self.conv1(x), 2))
                run.history.torch.log_stats(x, 'conv1.out')
                x = F.relu(F.max_pool2d(self.conv2_drop(self.conv2(x)), 2))
                run.history.torch.log_stats(x, 'conv2.out')
                x = x.view(-1, args.n2 * 16)
                x = F.relu(self.fc1(x))
                run.history.torch.log_stats(x, 'fc1.out')
                x = F.dropout(x, training=self.training)
                x = self.fc2(x)
                x = F.log_softmax(x, dim=0)
                run.history.torch.log_stats(x, 'fc2.out')
                return x
        """
        history = self._history()
        if history is None or not history._building_row():
            return

        if isinstance(variable_or_module, torch.autograd.Variable):
            if name is None:
                raise wandb.Error('Need a name to log stats for a Variable.')
            var = variable_or_module
            if values:
                self.log_tensor_stats(var.data, prefix+name)
            if gradients:
                self._hook_variable_gradient_stats(var, prefix+name+':grad')
        elif isinstance(variable_or_module, torch.nn.Module):
            module = variable_or_module
            if name is not None:
                prefix = prefix + name
            for name, parameter in module.named_parameters():
                self.log_stats(parameter, name=name, prefix=prefix, values=values, gradients=gradients)
        else:
            cls = type(var)
            raise TypeError('Expected torch.autograd.Variable or torch.nn.Module, not {}.{}'.format(cls.__module__, cls.__name__))

    def log_tensor_stats(self, tensor, name):
        """Add distribution statistics on a tensor's elements to the current History entry
        """
        if not hasattr(tensor, 'shape'):  # checking for inheritance from _TensorBase didn't work for some reason
            cls = type(tensor)
            raise TypeError('Expected Tensor, not {}.{}'.format(cls.__module__, cls.__name__))
        history = self._history()
        if history is None or not history._building_row():
            return

        flat = tensor.view(-1)
        l = len(flat)
        # kthvalue uses 1-based indexing for some reason
        i0_05 = max(1, min(int(round(0.05*l)), l))
        i0_95 = max(1, min(int(round(0.95*l)), l))
        history.update_row({
            name+'-0.00': tensor.min(),
            name+'-0.05': flat.kthvalue(i0_05)[0][0],
            name+'-0.50': tensor.median(),
            name+'-0.95': flat.kthvalue(i0_95)[0][0],
            name+'-1.00': tensor.max(),
            name+'-mean': tensor.mean(),
            name+'-stddev': tensor.std()
        })

    def _hook_variable_gradient_stats(self, var, name):
        """Logs a Variable's gradient's distribution statistics next time backward()
        is called on it.
        """
        if not isinstance(var, torch.autograd.Variable):
            cls = type(var)
            raise TypeError('Expected torch.Variable, not {}.{}'.format(cls.__module__, cls.__name__))

        handle = self._hook_handles.get(name)
        if handle is not None and _torch_hook_handle_is_valid(handle):
            raise ValueError('A hook has already been set under name "{}"'.format(name))

        def callback(grad):
            self.log_tensor_stats(grad.data, name)
            self.unhook(name)

        handle = var.register_hook(callback)
        self._hook_handles[name] = handle
        return handle

    def unhook(self, name):
        handle = self._hook_handles.pop(name)
        handle.remove()


def _torch_hook_handle_is_valid(handle):
    d = handle.hooks_dict_ref()
    if d is None:
        return False
    else:
        return handle.id in d