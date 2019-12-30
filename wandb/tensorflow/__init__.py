from copy import deepcopy

import tensorflow as tf

from wandb import util
from wandb.apis.file_stream import Chunk
from wandb.data_types import history_dict_to_json
from wandb.tensorboard import *
import wandb
try:
    from tensorflow.train import summary_iterator
except ImportError:
    from tensorflow.compat.v1.train import summary_iterator


if hasattr(tf.estimator, 'SessionRunHook'):
    # In tf 1.14 and beyond, SessionRunHook is in the estimator package.
    SessionRunHook = tf.estimator.SessionRunHook
else:
    # In older versions it's in train.
    SessionRunHook = tf.train.SessionRunHook


class WandbHook(SessionRunHook):
    def __init__(self, summary_op=None, steps_per_log=1000, history=None):
        self._summary_op = summary_op
        self._steps_per_log = steps_per_log
        # TODO(adrian): might be better to set this to wandb.run.history here
        # because that is the de facto default.
        self._history = history

    def begin(self):
        if self._summary_op is None:
            self._summary_op = tf.summary.merge_all()
        self._step = -1

    def before_run(self, run_context):
        self._step += 1
        return tf.train.SessionRunArgs({"summary": self._summary_op})

    def after_run(self, run_context, run_values):
        if self._step % self._steps_per_log == 0:
            log(run_values.results["summary"], history=self._history)


def stream_tfevents(path, file_api, run, step=0, namespace=""):
    """Parses and streams a tfevents file to the server"""
    last_step = 0
    row = {}
    buffer = []
    last_row = {}
    global_step_key = namespaced_tag("global_step", namespace)
    try:
        for summary in summary_iterator(path):
            parsed = tf_summary_to_dict(summary, namespace=namespace)
            if last_step != parsed[global_step_key]:
                last_step = parsed[global_step_key]
                if len(row) > 3:  # Must have more than _timestamp, _step, and global_step
                    step += 1
                    row["_step"] = step
                    last_row = history_dict_to_json(run, deepcopy(row))
                    file_api.push("wandb-history.jsonl", util.json_dumps_safer_history(last_row))
                    row = {}
            row.update(parsed)
    except tf.errors.DataLossError:
        wandb.termwarn("Found a truncated record in tfevents file, stopping parse")
    step += 1
    row["_step"] = step
    last_row = history_dict_to_json(run, deepcopy(row))
    file_api.push("wandb-history.jsonl", util.json_dumps_safer_history(last_row))
    return last_row


__all__ = ['log', 'patch', 'stream_tfevents', 'WandbHook']
