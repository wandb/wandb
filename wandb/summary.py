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

DEEP_SUMMARY_FNAME = 'wandb.h5'
SUMMARY_FNAME = 'wandb-summary.json'
H5_TYPES = ("numpy.ndarray", "tensorflow.Tensor", "pytorch.Tensor")

h5py = util.get_module("h5py")
np = util.get_module("numpy")


class NestedDict(object):
    """Nested dict-like object that reports "set" operations to a root object.
    """
    def __init__(self, root=None, path=()):
        if root is None:
            self._root = self
        else:
            self._root = root
        self._path = path
        self._dict = {}

    def _mark_dirty(self, path):
        raise NotImplementedError

    def __getitem__(self, k):
        return self._dict[k]

    def __contains__(self, k):
        return k in self._dict

    def __setitem__(self, k, v):
        path = self._path + (k,)

        if isinstance(v, dict):
            self._dict[k] = NestedDict(self._root, path)
            self._dict[k].update(v)
        else:
            self._dict[k] = v

        if self._root is not self:
            self._root._mark_dirty(path)

        return v

    def __delitem__(self, k):
        del self._dict[k]
        self._root._mark_dirty(self._path + (k,))

    def update(self, d):
        for k, v in six.iteritems(d):
            self[k] = v


class Summary(NestedDict):
    """Used to store summary metrics during and after a run."""

    def __init__(self, run, summary=None):
        super(Summary, self).__init__()
        self._run = run
        self._h5_path = os.path.join(self._run.dir, DEEP_SUMMARY_FNAME)
        # Lazy load the h5 file
        self._h5 = None
        self._locked_keys = set()

        # Mirrored version of self._dict that gets written to JSON
        # kept up to date by self._mark_dirty().
        self._json_dict = {}

        if summary is not None:
            self.update(summary)

    def _write(self, commit=False):
        raise NotImplementedError

    def get(self, k, default=None):
        raise NotImplementedError  # XXX
        return self._summary.get(k.strip(), default)

    def __setitem__(self, k, v):
        k = k.strip()
        super(Summary, self).__setitem__(k, v)
        self._locked_keys.add(k)
        self._write()
        return v

    def __setattr__(self, k, v):
        if k.startswith("_"):
            super(Summary, self).__setattr__(k, v)
        else:
            self[k] = v
            return v

    def __getattr__(self, k):
        if k.startswith("_"):
            return super(Summary, self).__getattr__(k)
        else:
            return self[k]

    def __delitem__(self, k):
        """
        h5_key = "summary/" + k.strip()
        if self._h5 and h5_key in self._h5:
            del self._h5[h5_key]
            self._h5.flush()
        """
        # XXX remove from self._locked_keys
        del super(Summary, self)[k.strip()]
        self._write()

    def __repr__(self):
        return repr(self._dict)

    def keys(self):
        return self._dict.keys()

    def update(self, key_vals=None, overwrite=True):
        """Passing overwrite=True locks any keys that are passed in.

        Locked keys can only be overwritten by passing overwrite=True.
        """
        if key_vals:
            write_keys = set(key_vals.keys())
            if not overwrite:
                # Overwrite keys that haven't been set even if they're in
                # locked keys. May not be necessary if we update locked keys
                # in del.
                write_keys -= self._locked_keys & set(self._dict.keys())
            write_key_vals = dict((k, key_vals[k]) for k in write_keys)
            super(Summary, self).update(write_key_vals)
            if overwrite:
                self._locked_keys += write_keys

        """
            for k, v in six.iteritems(key_vals):
                key = k.strip()
                if overwrite or key not in self._summary or key not in self._locked_keys:
                    summary[key] = v
                if overwrite:
                    self._locked_keys.add(key)
        self._summary.update(summary)
        """
        self._write(commit=True)

    def _mark_dirty(self, path):
        last_dict = None
        value = self
        for i, key in enumerate(path):
            if key in value:
                last_dict = value
                print(path, key, value)
                value = value[key]

        # XXX i and key may not be set
        if i == len(path):  # set or updated value
            json_dict = self._json_dict
            for key in path[:-1]:
                json_dict = json_dict[key]
            json_dict[path[-1]] = self._encode(value, path)
        else:  # deleted the key at `path`
            assert i == (len(path) - 1), \
                'Nonexistant path {} marked dirty but only {} exists.'.format(path, path[:i])





    def write_h5(self, key, val):
        # ensure the file is open
        self.open_h5()

        if not self._h5:
            wandb.termerror("Storing tensors in summary requires h5py")
        else:
            try:
                del self._h5["summary/" + key]
            except KeyError:
                pass
            self._h5["summary/" + key] = val
            self._h5.flush()

    def read_h5(self, key, val=None):
        # ensure the file is open
        self.open_h5()

        if not self._h5:
            wandb.termerror("Reading tensors from summary requires h5py")
        else:
            return self._h5.get("summary/" + key, val)

    def open_h5(self):
        if not self._h5 and h5py:
            self._h5 = h5py.File(self._h5_path, 'a', libver='latest')

    def _decode(self, k, v):
        """Decode a `dict` encoded by `Summary._encode()`, loading h5 objects.

        h5 objects may be very large, so we don't load them automatically.
        """
        if isinstance(v, dict):
            if v.get("_type") in H5_TYPES:
                return self.read_h5(k, v)
            elif v.get("_type") == 'data-frame':
                wandb.termerror(
                    'This data frame was saved via the wandb data API. Contact support@wandb.com for help.')
                return None
            # TODO: transform wandb objects and plots
            else:
                return {key: self._decode(k + "." + key, value) for (key, value) in v.items()}
        else:
            return v

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
            if util.is_pandas_data_frame(value):
                return util.encode_data_frame(key, value, self._run)
            else:
                path = ".".join(path_from_root)
                friendly_value, converted = util.json_friendly(data_types.val_to_json(key, value))
                json_value, compressed = util.maybe_compress_summary(friendly_value, util.get_h5_typename(value))
                if compressed:
                    self.write_h5(path, friendly_value)

                return json_value
        """
            if isinstance(value, dict):
                json_child[key], converted = util.json_friendly(
                    self._encode(value, path_from_root + [key]))
            else:
        """


def download_h5(run, entity=None, project=None, out_dir=None):
    api = Api()
    meta = api.download_url(project or api.settings(
        "project"), DEEP_SUMMARY_FNAME, entity=entity or api.settings("entity"), run=run)
    if meta and 'md5' in meta and meta['md5'] is not None:
        # TODO: make this non-blocking
        wandb.termlog("Downloading summary data...")
        path, res = api.download_write_file(meta, out_dir=out_dir)
        return path


def upload_h5(file, run, entity=None, project=None):
    api = Api()
    wandb.termlog("Uploading summary data...")
    api.push({os.path.basename(file): open(file, 'rb')}, run=run, project=project,
             entity=entity)


class FileSummary(Summary):
    def __init__(self, run):
        super(FileSummary, self).__init__(run)
        self._fname = os.path.join(run.dir, SUMMARY_FNAME)
        self.load()

    def load(self):
        try:
            self._summary = json.load(open(self._fname))
        except (IOError, ValueError):
            self._summary = {}

    def _write(self, commit=False):
        # TODO: we just ignore commit to ensure backward capability
        with open(self._fname, 'w') as f:
            s = util.json_dumps_safer(self._json_dict, indent=4)
            f.write(s)
            f.write('\n')
        if self._h5:
            self._h5.close()
            self._h5 = None


class HTTPSummary(Summary):
    def __init__(self, run, client, summary=None):
        super(HTTPSummary, self).__init__(run, summary=summary)
        self._run = run
        self._client = client
        self._started = time.time()

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
