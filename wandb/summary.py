import json
import os

import wandb
from wandb import util
from wandb.meta import Meta
from wandb.media import Image
from gql import gql
import six

SUMMARY_FNAME = 'wandb-summary.json'


class Summary(object):
    """Used to store summary metrics during and after a run."""

    def __init__(self, **kwargs):
        self._summary = kwargs.get("summary") or {}

    def _write(self, commit=False):
        raise NotImplementedError

    def _transform(self, v):
        if isinstance(v, wandb.Histogram):
            return wandb.Histogram.transform(v)
        else:
            return v

    def __getitem__(self, k):
        return self._summary[k]

    def __setitem__(self, k, v):
        self._summary[k] = self._transform(v)
        self._write()

    def __setattr__(self, k, v):
        if k.startswith("_"):
            super(Summary, self).__setattr__(k, v)
        else:
            self._summary[k] = self._transform(v)
            self._write()

    def __getattr__(self, k):
        if k.startswith("_"):
            super(Summary, self).__getattr__(k)
        else:
            return self._summary[k]

    def __delitem__(self, k):
        del self._summary[k]
        self._write()

    def __repr__(self):
        return str(self._summary)

    def get(self, k, default=None):
        return self._summary.get(k, default)

    def update(self, key_vals=None):
        summary = {}
        if key_vals:
            for k, v in six.iteritems(key_vals):
                if isinstance(v, Image) or (isinstance(v, dict) and v.get("_type") == "image"):
                    continue
                summary[k] = self._transform(v)
        self._summary.update(summary)
        self._write(commit=True)


class FileSummary(Summary):
    def __init__(self, out_dir="."):
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
            s = util.json_dumps_safer(self._summary, indent=4)
            f.write(s)
            f.write('\n')


class HTTPSummary(Summary):
    def __init__(self, client, run_storage_id, summary={}):
        print("SUPER", summary)
        super(HTTPSummary, self).__init__(summary=summary)
        self._run_storage_id = run_storage_id
        self._client = client
        print("INIT SUMMARY")

    def _write(self, commit=False):
        mutation = gql('''
        mutation UpsertBucket( $id: String, $summaryMetrics: JSONString) {
            upsertBucket(input: { id: $id, summaryMetrics: $summaryMetrics}) {
                bucket { id }
            }
        }
        ''')
        if commit:
            res = self._client.execute(mutation, variable_values={
                'id': self._run_storage_id, 'summaryMetrics': util.json_dumps_safer(self._summary)})
            assert res['upsertBucket']['bucket']['id']
        else:
            return False
