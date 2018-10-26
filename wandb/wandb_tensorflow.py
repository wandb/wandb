
# New tensorflow file writer that also updates wandb
#
# Usage:
# history = wandb.History()
# summary = wandb.Summary()
#
# summary_writer = WandbFileWriter(FLAGS.log_dir, wandb_summary=summary, wandb_history=history)
#
#     slim.learning.train(
#        train_op,
#        FLAGS.log_dir,
#        summary_writer=summary_writer)
#

import re

import six
import PIL
import tensorflow
try:
    pass
except ImportError:
    # If these fail, just die when someone tries to do something with TF.
    # Not using util.get_module() because the way these imports work seems a little
    # wonky.
    pass
import wandb.util


"""
Doesn't seem to work with modern versions of TensorFlow

#from tensorflow.python.summary.writer.event_file_writer import EventFileWriter

class WandbEventFileWriter(EventFileWriter):
    def __init__(self, logdir, max_queue=10, flush_secs=120,
                 filename_suffix=None, wandb_summary=None, wandb_history=None):
        self._wandb_summary = wandb_summary
        self._wandb_history = wandb_history
        super(WandbEventFileWriter, self).__init__(logdir, max_queue, flush_secs,
                                                   filename_suffix)

    def add_event(self, event):
        for v in event.summary.value:
            if v.simple_value:
                print("Tag: " + v.tag + " Val: " + str(v.simple_value))
                self._wandb_summary[v.tag] = v.simple_value

        super(WandbEventFileWriter, self).add_event(event)


class WandbFileWriter(tensorflow.summary.FileWriter):
    def __init__(self,
                 logdir,
                 graph=None,
                 max_queue=10,
                 flush_secs=120,
                 graph_def=None,
                 filename_suffix=None,
                 wandb_summary=None,
                 wandb_history=None):

        event_writer = WandbEventFileWriter(logdir, max_queue, flush_secs,
                                            filename_suffix, wandb_summary, wandb_history)

        super(WandbFileWriter, self).__init__(event_writer, graph, graph_def)
"""


class WandbHook(tensorflow.train.SessionRunHook):
    """Untested hook for tensorflow.train.MonitoredTrainingSession

    Use like:

    with tensorflow.train.MonitoredTrainingSession(
        checkpoint_dir=FLAGS.train_dir,
        hooks=[
            tf.train.StopAtStepHook(last_step=FLAGS.max_steps),
            _WandbHook(tf.summary.merge_all(), steps_per_log=FLAGS.log_frequency)]) as mon_sess:
        while not mon_sess.should_stop():
            mon_sess.run(train_op)
    """
    def __init__(self, summary_op, steps_per_log=100, history=None):
        self._summary_op = summary_op
        self._steps_per_log = steps_per_log
        if history is None:
            self._history = wandb.run.history
        else:
            self._history = history

    def begin(self):
        self._step = -1

    def before_run(self, run_context):
        self._step += 1
        return tensorflow.train.SessionRunArgs({"summary": self._summary_op})

    def after_run(self, run_context, run_values):
        if self._step % self._steps_per_log == 0:
            self._history.add(tf_summary_to_dict(run_values.results['summary']))


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
    if isinstance(tf_summary_str_or_pb, tensorflow.summary.Summary):
        summary_pb = tf_summary_str_or_pb
    else:
        summary_pb = tensorflow.summary.Summary()
        summary_pb.ParseFromString(tf_summary_str_or_pb)

    summary_values = {}
    for value in summary_pb.value:
        kind = value.WhichOneof("value")
        if kind == "simple_value":
            summary_values[value.tag] = value.simple_value
        elif kind == "image":
            image = wandb.Image(PIL.Image.open(six.BytesIO(value.image.encoded_image_string)))
            tag_idx = value.tag.rsplit('/', 1)
            if len(tag_idx) > 1 and tag_idx[1].isdigit():
                tag, idx = tag_idx
                summary_values.setdefault(history_image_key(tag), []).append(image)
            else:
                summary_values[history_image_key(value.tag)] = image

    return summary_values


def log_summary(wandb_history, tf_summary_str):
    wandb_history.log(tf_summary_to_dict(tf_summary_str))