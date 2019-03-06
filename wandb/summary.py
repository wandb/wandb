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


class Summary(object):
    """Used to store summary metrics during and after a run."""

    def __init__(self, run, summary=None):
        self._run = run
        self._summary = summary or {}
        self._h5_path = os.path.join(self._run.dir, DEEP_SUMMARY_FNAME)
        # Lazy load the h5 file
        self._h5 = None
        self._locked_keys = set()

        # Mapping of Python `id()`'s' to dicts representing large objects that
        # were present when we last encoded this summary. We use this to keep 
        # track of what we need to update the next time we write this summary.
        # This means that for many types of object we assume that once
        # they've been set in the summary they don't change.
        #
        # TODO(adrian): right now we only use this for DataFrames. Other large
        # objects (h5 stuff, images) should probably go in here as well.
        self._encoded_objects = {}

    def _write(self, commit=False):
        raise NotImplementedError

    def __getitem__(self, k):
        return self._decode(k, self._summary[k])

    def __setitem__(self, k, v):
        key = k.strip()
        self._summary[key] = v
        self._locked_keys.add(key)
        self._write()

    def __setattr__(self, k, v):
        if k.startswith("_"):
            super(Summary, self).__setattr__(k, v)
        else:
            key = k.strip()
            self._summary[key] = v
            self._locked_keys.add(key)
            self._write()

    def __getattr__(self, k):
        if k.startswith("_"):
            return super(Summary, self).__getattr__(k)
        else:
            # TODO(adrian): should probably get rid of the strip()'s here.
            return self._decode(k.strip(), self._summary[k.strip()])

    def __delitem__(self, k):
        h5_key = "summary/" + k.strip()
        if self._h5 and h5_key in self._h5:
            del self._h5[h5_key]
            self._h5.flush()
        del self._summary[k.strip()]
        self._write()

    def __repr__(self):
        return str(self._summary)

    def keys(self):
        return self._summary.keys()

    def get(self, k, default=None):
        return self._summary.get(k.strip(), default)

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
            elif v.get("_type") == 'parquet':
                wandb.termerror(
                    'This data frame was saved via the wandb data API. Contact support@wandb.com for help.')
                return None
            # TODO: transform wandb objects and plots
            else:
                return {key: self._decode(k + "." + key, value) for (key, value) in v.items()}
        else:
            return v

    def get_path(self, *path):
        d = self._summary
        for key in path:
            d = d.get(key)

        return d

    def _encode(self, child=None, path_from_root=[], json_root=None):
        """Normalize, compress, and encode sub-objects for backend storage.

        This is not threadsafe.

        child: Summary `dict` to encode. Defaults to `self._summary` but may
            be any sub-`dict` instead.
        path_from_root: `list` of key strings from the top-level summary to the
            current `child`.
        json_root: The new root dictionary for JSON encoding.

        Returns:
            A new tree of dict's with large objects replaced with dictionaries
            with "_type" entries that say which type the original data was.
        """

        # Constructs a new `dict` tree in `json_child` that discards and/or
        # encodes objects that aren't JSON serializable.

        json_child = {}

        if child is None:
            child = self._summary

        if json_root is None:
            json_root = json_child

        for key, value in six.iteritems(child):
            path = ".".join(path_from_root + [key])
            if isinstance(value, dict):
                json_child[key], converted = util.json_friendly(
                    self._encode(value, path_from_root + [key], json_root))
            else:
                vid = id(value)
                if vid not in self._encoded_objects:
                    if util.is_pandas_data_frame(value):
                        self._encoded_objects[vid] = util.encode_data_frame(key, value, self._run)
                    else:
                        friendly_val, converted = util.json_friendly(
                            data_types.val_to_json(key, value))
                        self._encoded_objects[vid], compressed = util.maybe_compress_summary(
                            friendly_val, util.get_h5_typename(value))
                        if compressed:
                            self.write_h5(path, friendly_val)

                json_child[key] = self._encoded_objects[vid]

        return json_child

    def update(self, key_vals=None, overwrite=True):
        # Passing overwrite=True locks any keys that are passed in
        # Locked keys can only be overwritten by passing overwrite=True
        summary = {}
        if key_vals:
            for k, v in six.iteritems(key_vals):
                key = k.strip()
                if overwrite or key not in self._summary or key not in self._locked_keys:
                    summary[key] = v
                if overwrite:
                    self._locked_keys.add(key)
        self._summary.update(summary)
        self._write(commit=True)


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
            s = util.json_dumps_safer(self._encode(), indent=4)
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
                'id': self._run.storage_id, 'summaryMetrics': util.json_dumps_safer(self._encode())})
            assert res['upsertBucket']['bucket']['id']
            entity, project, run = self._run.path
            if os.path.exists(self._h5_path) and os.path.getmtime(self._h5_path) >= self._started:
                upload_h5(self._h5_path, run, entity=entity, project=project)
        else:
            return False
