import json
import os
import sys
import time
import requests

import wandb
from wandb import util
from wandb.meta import Meta
from wandb.media import Image
from wandb.apis.internal import Api
from gql import gql
import six

SUMMARY_FNAME = 'wandb-summary.json'
DEEP_SUMMARY_FNAME = 'wandb.h5'
H5_TYPES = ("numpy.ndarray", "tensorflow.Tensor",
            "pytorch.Tensor", "pandas.DataFrame")

try:
    import h5py
except ImportError:
    h5py = None


class Summary(object):
    """Used to store summary metrics during and after a run."""

    def __init__(self, **kwargs):
        self._out_dir = kwargs.get("out_dir") or "."
        self._summary = kwargs.get("summary") or {}
        self._h5_path = os.path.join(
            self._out_dir, DEEP_SUMMARY_FNAME)
        # Lazy load the h5 file
        self._h5 = None

    def _write(self, commit=False):
        raise NotImplementedError

    def _transform(self, k, v=None, write=True):
        if not write and isinstance(v, dict):
            if v.get("_type") in H5_TYPES:
                return self.read_h5(k, v)
            else:
                return {key: self._transform(k + "." + key, value, write=False) for (key, value) in v.items()}

        if isinstance(v, wandb.Histogram):
            return wandb.Histogram.transform(v)
        elif isinstance(v, wandb.Graph):
            return wandb.Graph.transform(v)
        else:
            return v

    def __getitem__(self, k):
        return self._transform(k, self._summary[k], write=False)

    def __setitem__(self, k, v):
        self._summary[k] = self._transform(k, v)
        self._write()

    def __setattr__(self, k, v):
        if k.startswith("_"):
            super(Summary, self).__setattr__(k, v)
        else:
            self._summary[k] = self._transform(k, v)
            self._write()

    def __getattr__(self, k):
        if k.startswith("_"):
            return super(Summary, self).__getattr__(k)
        else:
            return self._transform(k, self._summary[k], write=False)

    def __delitem__(self, k):
        val = self._summary[k]
        if isinstance(val, dict) and val.get("_type") in H5_TYPES:
            if not self._h5:
                wandb.termerror("Deleting tensors in summary requires h5py")
            else:
                del self._h5["summary/" + k]
                self._h5.flush()
        del self._summary[k]
        self._write()

    def __repr__(self):
        return str(self._summary)

    def keys(self):
        return self._summary.keys()

    def get(self, k, default=None):
        return self._summary.get(k, default)

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

    def read_h5(self, key, val):
        # ensure the file is open
        self.open_h5()

        if not self._h5:
            wandb.termerror("Reading tensors from summary requires h5py")
        else:
            return self._h5["summary/" + key]

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
                res[key], converted, transformed = util.json_friendly(
                    self.convert_json(value, root_path + [key]))
            else:
                res[key], converted, transformed = util.json_friendly(value)
                if transformed:
                    if res[key]["_type"] == "pytorch.Tensor":
                        value = value.numpy()
                    elif res[key]["_type"] == "tensorflow.Tensor":
                        value = value.eval()
                    self.write_h5(path, value)
        self._summary = res
        return res

    def update(self, key_vals=None):
        summary = {}
        if key_vals:
            for k, v in six.iteritems(key_vals):
                # TODO: proper image support in summary
                is_image = isinstance(v, Image) or (
                    isinstance(v, list) and isinstance(v[0], Image))
                if is_image or (isinstance(v, dict) and v.get("_type") == "image"):
                    continue
                summary[k] = self._transform(k, v)
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
    # TODO: unfortunate
    slug = "/".join([project or api.settings("project"), run])
    wandb.termlog("Uploading summary data...")
    api.push(slug, {os.path.basename(file): open(file, 'rb')},
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
