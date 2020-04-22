from __future__ import unicode_literals

import json
import os
import sys
import time
import requests

from gql import gql
import six

import wandb
from wandb import util
from wandb import data_types
from wandb.meta import Meta
from wandb.apis.internal import Api
from six import string_types


DEEP_SUMMARY_FNAME = 'wandb.h5'
SUMMARY_FNAME = 'wandb-summary.json'
H5_TYPES = ("numpy.ndarray", "tensorflow.Tensor", "torch.Tensor")

h5py = util.get_module("h5py")
np = util.get_module("numpy")


class SummarySubDict(object):
    """Nested dict-like object that proxies read and write operations through a root object.

    This lets us do synchronous serialization and lazy loading of large values.
    """

    def __init__(self, root=None, path=()):
        if root is None:
            self._root = self
        else:
            self._root = root
        self._path = tuple(path)
        self._dict = {}
        self._json_dict = {}

        # We use this to track which keys the user has set explicitly
        # so that we don't automatically overwrite them when we update
        # the summary from the history.
        self._locked_keys = set()

    def __setattr__(self, k, v):
        k = k.strip()
        if k.startswith("_"):
            object.__setattr__(self, k, v)
        else:
            self[k] = v

    def __getattr__(self, k):
        k = k.strip()
        if k.startswith("_"):
            return object.__getattribute__(self, k)
        else:
            return self[k]

    def _root_get(self, path, child_dict):
        """Load a value at a particular path from the root.

        This should only be implemented by the "_root" child class.

        We pass the child_dict so the item can be set on it or not as
        appropriate. Returning None for a nonexistant path wouldn't be
        distinguishable from that path being set to the value None.
        """
        raise NotImplementedError

    def _root_set(self, path, new_keys_values):
        """Set a value at a particular path in the root.

        This should only be implemented by the "_root" child class.
        """
        raise NotImplementedError

    def _root_del(self, path):
        """Delete a value at a particular path in the root.

        This should only be implemented by the "_root" child class.
        """
        raise NotImplementedError

    def _write(self, commit=False):
        # should only be implemented on the root summary
        raise NotImplementedError

    def keys(self):
        # _json_dict has the full set of keys, including those for h5 objects
        # that may not have been loaded yet
        return self._json_dict.keys()

    def get(self, k, default=None):
        if isinstance(k, string_types):
            k = k.strip()
        if k not in self._dict:
            self._root._root_get(self._path + (k,), self._dict)
        return self._dict.get(k, default)

    def items(self):
        # not all items may be loaded into self._dict, so we
        # have to build the sequence of items from scratch
        for k in self.keys():
            yield k, self[k]

    def __getitem__(self, k):
        if isinstance(k, string_types):
            k = k.strip()

        self.get(k)  # load the value into _dict if it should be there
        return self._dict[k]

    def __contains__(self, k):
        if isinstance(k, string_types):
            k = k.strip()

        return k in self._json_dict

    def __setitem__(self, k, v):
        if isinstance(k, string_types):
            k = k.strip()

        path = self._path

        if isinstance(v, dict):
            self._dict[k] = SummarySubDict(self._root, path + (k,))
            self._root._root_set(path, [(k, {})])
            self._dict[k].update(v)
        else:
            self._dict[k] = v
            self._root._root_set(path, [(k, v)])

        self._locked_keys.add(k)

        self._root._write()

        return v

    def __delitem__(self, k):
        k = k.strip()
        del self._dict[k]
        self._root._root_del(self._path + (k,))

        self._root._write()

    def __repr__(self):
        # use a copy of _dict, except add placeholders for h5 objects, etc.
        # that haven't been loaded yet
        repr_dict = dict(self._dict)
        for k in self._json_dict:
            v = self._json_dict[k]
            if k not in repr_dict and isinstance(v, dict) and v.get('_type') in H5_TYPES:
                # unloaded h5 objects may be very large. use a placeholder for them
                # if we haven't already loaded them
                repr_dict[k] = '...'
            else:
                repr_dict[k] = self[k]

        return repr(repr_dict)

    def update(self, key_vals=None, overwrite=True):
        """Locked keys will be overwritten unless overwrite=False.

        Otherwise, written keys will be added to the "locked" list.
        """
        if key_vals:
            write_items = self._update(key_vals, overwrite)
            self._root._root_set(self._path, write_items)
        self._root._write(commit=True)

    def _update(self, key_vals, overwrite):
        if not key_vals:
            return

        key_vals = dict((k.strip(), v) for k, v in six.iteritems(key_vals))

        if overwrite:
            write_items = list(six.iteritems(key_vals))
            self._locked_keys.update(key_vals.keys())
        else:
            write_keys = set(key_vals.keys()) - self._locked_keys
            write_items = [(k, key_vals[k]) for k in write_keys]

        for key, value in write_items:
            if isinstance(value, dict):
                self._dict[key] = SummarySubDict(
                    self._root, self._path + (key,))
                self._dict[key]._update(value, overwrite)
            else:
                self._dict[key] = value

        return write_items


class Summary(SummarySubDict):
    """Store summary metrics (eg. accuracy) during and after a run.

    You can manipulate this as if it's a Python dictionary but the keys
    get mangled. .strip() is called on them, so spaces at the beginning
    and end are removed.
    """

    def __init__(self, run, summary=None):
        super(Summary, self).__init__()
        self._run = run
        self._h5_path = os.path.join(self._run.dir, DEEP_SUMMARY_FNAME)
        # Lazy load the h5 file
        self._h5 = None

        # Mirrored version of self._dict with versions of values that get written
        # to JSON kept up to date by self._root_set() and self._root_del().
        self._json_dict = {}

        if summary is not None:
            self._json_dict = summary

    def _json_get(self, path):
        pass

    def _root_get(self, path, child_dict):
        json_dict = self._json_dict
        for key in path[:-1]:
            json_dict = json_dict[key]

        key = path[-1]
        if key in json_dict:
            child_dict[key] = self._decode(path, json_dict[key])

    def _root_del(self, path):
        json_dict = self._json_dict
        for key in path[:-1]:
            json_dict = json_dict[key]

        val = json_dict[path[-1]]
        del json_dict[path[-1]]
        if isinstance(val, dict) and val.get("_type") in H5_TYPES:
            if not h5py:
                wandb.termerror("Deleting tensors in summary requires h5py")
            else:
                self.open_h5()
                h5_key = "summary/" + '.'.join(path)
                del self._h5[h5_key]
                self._h5.flush()

    def _root_set(self, path, new_keys_values):
        json_dict = self._json_dict
        for key in path:
            json_dict = json_dict[key]

        for new_key, new_value in new_keys_values:
            json_dict[new_key] = self._encode(new_value, path + (new_key,))

    def write_h5(self, path, val):
        # ensure the file is open
        self.open_h5()

        if not self._h5:
            wandb.termerror("Storing tensors in summary requires h5py")
        else:
            try:
                del self._h5["summary/" + '.'.join(path)]
            except KeyError:
                pass
            self._h5["summary/" + '.'.join(path)] = val
            self._h5.flush()

    def read_h5(self, path, val=None):
        # ensure the file is open
        self.open_h5()

        if not self._h5:
            wandb.termerror("Reading tensors from summary requires h5py")
        else:
            return self._h5.get("summary/" + '.'.join(path), val)

    def open_h5(self):
        if not self._h5 and h5py:
            self._h5 = h5py.File(self._h5_path, 'a', libver='latest')

    def _decode(self, path, json_value):
        """Decode a `dict` encoded by `Summary._encode()`, loading h5 objects.

        h5 objects may be very large, so we won't have loaded them automatically.
        """
        if isinstance(json_value, dict):
            if json_value.get("_type") in H5_TYPES:
                return self.read_h5(path, json_value)
            elif json_value.get("_type") == 'data-frame':
                wandb.termerror(
                    'This data frame was saved via the wandb data API. Contact support@wandb.com for help.')
                return None
            # TODO: transform wandb objects and plots
            else:
                return SummarySubDict(self, path)
        else:
            return json_value

    def _encode(self, value, path_from_root):
        """Normalize, compress, and encode sub-objects for backend storage.

        value: Object to encode.
        path_from_root: `tuple` of key strings from the top-level summary to the
            current `value`.

        Returns:
            A new tree of dict's with large objects replaced with dictionaries
            with "_type" entries that say which type the original data was.
        """

        # Constructs a new `dict` tree in `json_value` that discards and/or
        # encodes objects that aren't JSON serializable.

        if isinstance(value, dict):
            json_value = {}
            for key, value in six.iteritems(value):
                json_value[key] = self._encode(value, path_from_root + (key,))
            return json_value
        else:
            path = ".".join(path_from_root)
            friendly_value, converted = util.json_friendly(data_types.val_to_json(self._run, path, value))
            json_value, compressed = util.maybe_compress_summary(friendly_value, util.get_h5_typename(value))
            if compressed:
                self.write_h5(path_from_root, friendly_value)

            return json_value


def download_h5(run_id, entity=None, project=None, out_dir=None):
    api = Api()
    meta = api.download_url(project or api.settings(
        "project"), DEEP_SUMMARY_FNAME, entity=entity or api.settings("entity"), run=run_id)
    if meta and 'md5' in meta and meta['md5'] is not None:
        # TODO: make this non-blocking
        wandb.termlog("Downloading summary data...")
        path, res = api.download_write_file(meta, out_dir=out_dir)
        return path


def upload_h5(file, run_id, entity=None, project=None):
    api = Api()
    wandb.termlog("Uploading summary data...")
    with open(file, 'rb') as f:
        api.push({os.path.basename(file): f}, run=run_id, project=project,
                entity=entity)


class FileSummary(Summary):
    def __init__(self, run):
        super(FileSummary, self).__init__(run)
        self._fname = os.path.join(run.dir, SUMMARY_FNAME)
        self.load()

    def load(self):
        try:
            with open(self._fname) as f:
                self._json_dict = json.load(f)
        except (IOError, ValueError):
            self._json_dict = {}

    def _write(self, commit=False):
        # TODO: we just ignore commit to ensure backward capability
        with open(self._fname, 'w') as f:
            f.write(util.json_dumps_safer(self._json_dict))
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        if self._h5:
            self._h5.close()
            self._h5 = None
        if wandb.run and wandb.run._jupyter_agent:
            wandb.run._jupyter_agent.start()


class HTTPSummary(Summary):
    def __init__(self, run, client, summary=None):
        super(HTTPSummary, self).__init__(run, summary=summary)
        self._run = run
        self._client = client
        self._started = time.time()

    def load(self):
        pass

    def open_h5(self):
        if not self._h5 and h5py:
            download_h5(self._run.id, entity=self._run.entity, project=self._run.project, out_dir=self._run.dir)
        super(HTTPSummary, self).open_h5()

    def _write(self, commit=False):
        mutation = gql('''
        mutation UpsertBucket( $id: String, $summaryMetrics: JSONString) {
            upsertBucket(input: { id: $id, summaryMetrics: $summaryMetrics}) {
                bucket { id }
            }
        }
        ''')
        if commit:
            if self._h5:
                self._h5.close()
                self._h5 = None
            res = self._client.execute(mutation, variable_values={
                'id': self._run.storage_id, 'summaryMetrics': util.json_dumps_safer(self._json_dict)})
            assert res['upsertBucket']['bucket']['id']
            entity, project, run = self._run.path
            if os.path.exists(self._h5_path) and os.path.getmtime(self._h5_path) >= self._started:
                upload_h5(self._h5_path, run, entity=entity, project=project)
        else:
            return False
