import time
import os
import re
import six
import sys
import wandb

tensorboardX_loaded = "tensorboardX" in sys.modules
tensorflow_loaded = "tensorflow" in sys.modules
if not tensorboardX_loaded and not tensorflow_loaded:
    tensorboardX_loaded = wandb.util.get_module("tensorflowX") is not None

if tensorboardX_loaded:
    from tensorboardX.proto.summary_pb2 import Summary
    from tensorboardX.proto.event_pb2 import Event
else:
    from tensorflow.summary import Summary, Event


def patch(save=True, tensorboardX=tensorboardX_loaded):
    """Monkeypatches tensorboard or tensorboardX so that all events are logged to tfevents files and wandb.
    We save the tfevents files and graphs to wandb by default.

    Arguments:
        save, default: True - Passing False will skip sending events.
        tensorboardX, default: True if module can be imported - You can override this when calling patch
    """
    global Summary, Event
    if tensorboardX:
        tensorboard_module = "tensorboardX.writer"
        if tensorflow_loaded:
            wandb.termlog(
                "Found TensorboardX and tensorflow, pass tensorboardX=False to patch regular tensorboard.")
        from tensorboardX.proto.summary_pb2 import Summary
        from tensorboardX.proto.event_pb2 import Event
    else:
        tensorboard_module = "tensorflow.python.summary.writer.writer"
        from tensorflow.summary import Summary, Event

    writers = set()

    def _add_event(self, event, step, walltime=None):
        event.wall_time = time.time() if walltime is None else walltime
        if step is not None:
            event.step = int(step)
            try:
                # TensorboardX uses _file_name
                if hasattr(self.event_writer._ev_writer, "_file_name"):
                    name = self.event_writer._ev_writer._file_name
                else:
                    name = self.event_writer._ev_writer.FileName().decode("utf-8")
                writers.add(name)
                # This is a little hacky, there is a case where the log_dir changes.
                # Because the events files will have the same names in sub directories
                # we simply overwrite the previous symlink in wandb.save if the log_dir
                # changes.
                log_dir = os.path.dirname(os.path.commonprefix(list(writers)))
                filename = os.path.basename(name)
                # Tensorboard loads all tfevents files in a directory and prepends
                # their values with the path.  Passing namespace to log allows us
                # to nest the values in wandb
                namespace = name.replace(filename, "").replace(
                    log_dir, "").strip(os.sep)
                if save:
                    wandb.save(name, base_path=log_dir)
                    wandb.save(os.path.join(log_dir, "*.pbtxt"),
                               base_path=log_dir)
                log(event, namespace=namespace, step=event.step)
            except Exception as e:
                wandb.termerror("Unable to log event %s" % e)
                # six.reraise(type(e), e, sys.exc_info()[2])
        self.event_writer.add_event(event)
    writer = wandb.util.get_module(tensorboard_module)
    writer.SummaryToEventTransformer._add_event = _add_event


def log(tf_summary_str, **kwargs):
    namespace = kwargs.get("namespace")
    if namespace is not None:
        del kwargs["namespace"]
    wandb.log(tf_summary_to_dict(tf_summary_str, namespace), **kwargs)


def history_image_key(key, namespace=""):
    """Converts invalid filesystem characters to _ for use in History keys.

    Unfortunately this means currently certain image keys will collide silently. We
    implement this mapping up here in the TensorFlow stuff rather than in the History
    stuff so that we don't have to store a mapping anywhere from the original keys to
    the safe ones.
    """
    return namespaced_tag(re.sub(r'[/\\]', '_', key), namespace)


def namespaced_tag(tag, namespace=""):
    namespace = (namespace or "").replace(tag, "")
    return tag + namespace


def tf_summary_to_dict(tf_summary_str_or_pb, namespace=""):
    """Convert a Tensorboard Summary to a dictionary

    Accepts either a tensorflow.summary.Summary
    or one encoded as a string.
    """
    values = {}
    if isinstance(tf_summary_str_or_pb, Summary):
        summary_pb = tf_summary_str_or_pb
    elif isinstance(tf_summary_str_or_pb, Event):
        summary_pb = tf_summary_str_or_pb.summary
        values["global_step"] = tf_summary_str_or_pb.step
        values["_timestamp"] = tf_summary_str_or_pb.wall_time
    else:
        summary_pb = Summary()
        summary_pb.ParseFromString(tf_summary_str_or_pb)

    for value in summary_pb.value:
        kind = value.WhichOneof("value")
        if kind == "simple_value":
            values[namespaced_tag(value.tag, namespace)] = value.simple_value
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
        # Coming soon...
        # elif kind == "audio":
        #    audio = wandb.Audio(six.BytesIO(value.audio.encoded_audio_string),
        #                        sample_rate=value.audio.sample_rate, content_type=value.audio.content_type)
        elif kind == "histo":
            first = value.histo.bucket_limit[0] + \
                value.histo.bucket_limit[0] - value.histo.bucket_limit[1]
            last = value.histo.bucket_limit[-2] + \
                value.histo.bucket_limit[-2] - value.histo.bucket_limit[-3]
            np_histogram = (list(value.histo.bucket), [
                first] + value.histo.bucket_limit[:-1] + [last])
            values[namespaced_tag(value.tag)] = wandb.Histogram(
                np_histogram=np_histogram)

    return values


__all__ = ["patch", "log", "tf_summary_to_dict", "history_image_key"]
