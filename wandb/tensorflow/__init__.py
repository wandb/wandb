import re

import six
import tensorflow as tf
import wandb.util
import wandb


class WandbHook(tf.train.SessionRunHook):
    def __init__(self, summary_op=None, steps_per_log=100):
        self._summary_op = summary_op
        self._steps_per_log = steps_per_log

    def begin(self):
        if self._summary_op is None:
            self._summary_op = tf.summary.merge_all()
        self._step = -1

    def before_run(self, run_context):
        self._step += 1
        return tf.train.SessionRunArgs({"summary": self._summary_op})

    def after_run(self, run_context, run_values):
        if self._step % self._steps_per_log == 0:
            log(run_values.results["summary"])


def history_image_key(key):
    """Converts invalid filesystem characters to _ for use in History keys.

    Unfortunately this means currently certain image keys will collide silently. We
    implement this mapping up here in the TensorFlow stuff rather than in the History
    stuff so that we don't have to store a mapping anywhere from the original keys to
    the safe ones.
    """
    return re.sub(r'[/\\]', '_', key)


def tf_summary_to_dict(tf_summary_str_or_pb):
    """Convert a TensorFlow Summary to a dictionary

    Accepts either a tensorflow.summary.Summary
    or one encoded as a string.
    """
    if isinstance(tf_summary_str_or_pb, tf.summary.Summary):
        summary_pb = tf_summary_str_or_pb
    else:
        summary_pb = tf.summary.Summary()
        summary_pb.ParseFromString(tf_summary_str_or_pb)

    values = {}
    for value in summary_pb.value:
        kind = value.WhichOneof("value")
        if kind == "simple_value":
            values[value.tag] = value.simple_value
        elif kind == "image":
            from PIL import Image
            image = wandb.Image(Image.open(
                six.BytesIO(value.image.encoded_image_string)))
            tag_idx = value.tag.rsplit('/', 1)
            if len(tag_idx) > 1 and tag_idx[1].isdigit():
                tag, idx = tag_idx
                values.setdefault(history_image_key(tag), []).append(image)
            else:
                values[history_image_key(value.tag)] = image
        elif kind == "histo":
            first = value.histo.bucket_limit[0] + \
                value.histo.bucket_limit[0] - value.histo.bucket_limit[1]
            last = value.histo.bucket_limit[-2] + \
                value.histo.bucket_limit[-2] - value.histo.bucket_limit[-3]
            np_histogram = (list(value.histo.bucket), [
                            first] + value.histo.bucket_limit[:-1] + [last])
            values[value.tag] = wandb.Histogram(np_histogram=np_histogram)

    return values


def log(tf_summary_str):
    wandb.log(tf_summary_to_dict(tf_summary_str))
