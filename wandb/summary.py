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

SUMMARY_FNAME = 'wandb-summary.json'
DEEP_SUMMARY_FNAME = 'wandb.h5'
H5_TYPES = ("numpy.ndarray", "tensorflow.Tensor",
            "pytorch.Tensor", "pandas.DataFrame")

h5py = util.get_module("h5py")
np = util.get_module("numpy")


class Summary(object):
    """Used to store summary metrics during and after a run."""

    def __init__(self, **kwargs):
        self._out_dir = kwargs.get("out_dir") or "."
        self._summary = kwargs.get("summary") or {}
        self._h5_path = os.path.join(
            self._out_dir, DEEP_SUMMARY_FNAME)
        # Lazy load the h5 file
        self._h5 = None
        self._locked_keys = set()

    def _write(self, commit=False):
        raise NotImplementedError

    def _transform(self, k, v=None, write=True):
        """Transforms keys json into rich objects for the data api"""
        if not write and isinstance(v, dict):
            if v.get("_type") in H5_TYPES:
                return self.read_h5(k, v)
            # TODO: transform wandb objects and plots
            else:
                return {key: self._transform(k + "." + key, value, write=False) for (key, value) in v.items()}

        return v

    def __getitem__(self, k):
        return self._transform(k, self._summary[k], write=False)

    def __setitem__(self, k, v):
        key = k.strip()
        self._summary[key] = self._transform(key, v)
        self._locked_keys.add(key)
        self._write()

    def __setattr__(self, k, v):
        if k.startswith("_"):
            super(Summary, self).__setattr__(k, v)
        else:
            key = k.strip()
            self._summary[key] = self._transform(key, v)
            self._locked_keys.add(key)
            self._write()

    def __getattr__(self, k):
        if k.startswith("_"):
            return super(Summary, self).__getattr__(k)
        else:
            return self._transform(k.strip(), self._summary[k.strip()], write=False)

    def __delitem__(self, k):
        val = self._summary[k.strip()]
        if isinstance(val, dict) and val.get("_type") in H5_TYPES:
            if not self._h5:
                wandb.termerror("Deleting tensors in summary requires h5py")
            else:
                del self._h5["summary/" + k.strip()]
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

    def convert_json(self, obj=None, root_path=[]):
        """Convert obj to json, summarizing larger arrays in JSON and storing them in h5."""
        res = {}
        obj = obj or self._summary
        for key, value in six.iteritems(obj):
            path = ".".join(root_path + [key])
            if isinstance(value, dict):
                res[key], converted = util.json_friendly(
                    self.convert_json(value, root_path + [key]))
            else:
                tmp_obj, converted = util.json_friendly(
                    data_types.val_to_json(key, value))
                res[key], compressed = util.maybe_compress_summary(
                    tmp_obj, util.get_h5_typename(value))
                if compressed:
                    self.write_h5(path, tmp_obj)

        self._summary = res
        return res

    def update(self, key_vals=None, overwrite=True):
        # Passing overwrite=True locks any keys that are passed in
        # Locked keys can only be overwritten by passing overwrite=True
        summary = {}
        if key_vals:
            for k, v in six.iteritems(key_vals):
                key = k.strip()
                if overwrite or key not in self._summary or key not in self._locked_keys:
                    summary[key] = self._transform(k.strip(), v)
                if overwrite:
                    self._locked_keys.add(key)
        self._summary.update(summary)
        self._write(commit=True)


def download_h5(run, entity=None, project=None, out_dir=None):
    api = Api()
    meta = api.download_url(project or api.settings(
        "project"), DEEP_SUMMARY_FNAME, entity=entity or api.settings("entity"), run=run)
    if meta:
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
    def __init__(self, out_dir="."):
        super(FileSummary, self).__init__(out_dir=out_dir)
        self._fname = os.path.join(out_dir, SUMMARY_FNAME)
        self.load()

    def load(self):
        try:
            self._summary = json.load(open(self._fname))
        except (IOError, ValueError):
            self._summary = {}

    def _write(self, commit=False):
        # TODO: we just ignore commit to ensure backward capability
        with open(self._fname, 'w') as f:
            s = util.json_dumps_safer(self.convert_json(), indent=4)
            f.write(s)
            f.write('\n')
        if self._h5:
            self._h5.close()
            self._h5 = None


class HTTPSummary(Summary):
    def __init__(self, client, run_storage_id, path="//", summary={}, out_dir="."):
        super(HTTPSummary, self).__init__(summary=summary, out_dir=out_dir)
        self._run_storage_id = run_storage_id
        self._path = path
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
                'id': self._run_storage_id, 'summaryMetrics': util.json_dumps_safer(self.convert_json())})
            assert res['upsertBucket']['bucket']['id']
            entity, project, run = self._path.split("/")
            if os.path.exists(self._h5_path) and os.path.getmtime(self._h5_path) >= self._started:
                upload_h5(self._h5_path, run, entity=entity, project=project)
        else:
            return False
