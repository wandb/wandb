import time
import os
import re
import six
import sys
import wandb

tensorboardX_loaded = "tensorboardX" in sys.modules
tensorflow_loaded = "tensorflow" in sys.modules
if not tensorboardX_loaded and not tensorflow_loaded:
    tensorboardX_loaded = wandb.util.get_module("tensorboardX") is not None

if tensorboardX_loaded:
    from tensorboardX.proto.summary_pb2 import Summary
else:
    try:
        from tensorboard.compat.proto.summary_pb2 import Summary
    except ImportError:
        from tensorflow.summary import Summary


def patch(save=True, tensorboardX=tensorboardX_loaded):
    """Monkeypatches tensorboard or tensorboardX so that all events are logged to tfevents files and wandb.
    We save the tfevents files and graphs to wandb by default.

    Arguments:
        save, default: True - Passing False will skip storing tfevent files.
        tensorboardX, default: True if module can be imported - You can override this when calling patch
    """

    tensorboard_c_module = "tensorflow.python.ops.gen_summary_ops"
    if tensorboardX:
        tensorboard_py_module = "tensorboardX.writer"
        if tensorflow_loaded:
            wandb.termlog(
                "Found tensorboardX and tensorflow, pass tensorboardX=False to patch regular tensorboard.")
    else:
        if wandb.util.get_module("tensorboard.summary.writer.event_file_writer") and not tensorflow_loaded:
            # If we haven't imported tensorflow, let's patch the python tensorboard writer
            tensorboard_py_module = "tensorboard.summary.writer.event_file_writer"
        else:
            # If we're using tensorflow >= 2.0 this patch won't be used, but we'll do it anyway
            tensorboard_py_module = "tensorflow.python.summary.writer.writer"

    writers = set()
    writer = wandb.util.get_module(tensorboard_py_module)

    def add_event(orig_event):
        """TensorboardX, TensorFlow <= 1.14 patch, and Tensorboard Patch"""

        def _add_event(self, event):
            orig_event(self, event)
            try:
                if hasattr(self, "_file_name"):
                    # Current Tensorboard
                    name = self._file_name
                elif hasattr(self, "_ev_writer"):
                    if hasattr(self._ev_writer, "FileName"):
                        # Legacy Tensorflow
                        name = self._ev_writer.FileName().decode("utf-8")
                    elif hasattr(self._ev_writer, "_file_name"):
                        # Current TensorboardX
                        name = self._ev_writer._file_name
                    else:
                        # Legacy TensorboardX
                        name = self._ev_writer._file_prefix
                else:
                    wandb.termerror(
                        "Couldn't patch tensorboard, email support@wandb.com with the tensorboard version you're using.")
                    writer.EventFileWriter.add_event = orig_event
                    return None
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
        return _add_event

    if writer:
        # This is for TensorboardX and PyTorch 1.1 python tensorboard logging
        writer.EventFileWriter.add_event = add_event(
            writer.EventFileWriter.add_event)
        wandb.patched["tensorboard"].append(tensorboard_py_module)

    # This configures TensorFlow 2 style Tensorboard logging
    c_writer = wandb.util.get_module(tensorboard_c_module)
    if c_writer:
        old_csfw_func = c_writer.create_summary_file_writer

        def new_csfw_func(*args, **kwargs):
            """Tensorboard 2+ hook for streaming events from the filesystem"""
            logdir = kwargs['logdir'].numpy()
            wandb.run.send_message(
                {"tensorboard": {"logdir": logdir.decode("utf8"), "save": save}})
            return old_csfw_func(*args, **kwargs)

        c_writer.create_summary_file_writer = new_csfw_func
        wandb.patched["tensorboard"].append(tensorboard_c_module)


def log(tf_summary_str, **kwargs):
    namespace = kwargs.get("namespace")
    if "namespace" in kwargs:
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
    if not namespace:
        return tag
    elif tag in namespace:
        # This happens with tensorboardX
        return namespace
    else:
        return namespace + "/" + tag


def tf_summary_to_dict(tf_summary_str_or_pb, namespace=""):
    """Convert a Tensorboard Summary to a dictionary

    Accepts either a tensorflow.summary.Summary
    or one encoded as a string.
    """
    values = {}

    if hasattr(tf_summary_str_or_pb, "summary"):
        summary_pb = tf_summary_str_or_pb.summary
        values[namespaced_tag("global_step", namespace)
               ] = tf_summary_str_or_pb.step
        values["_timestamp"] = tf_summary_str_or_pb.wall_time
    elif isinstance(tf_summary_str_or_pb, (str, bytes, bytearray)):
        summary_pb = Summary()
        summary_pb.ParseFromString(tf_summary_str_or_pb)
    else:
        if not hasattr(tf_summary_str_or_pb, "value"):
            raise ValueError(
                "Can't log %s, only Event, Summary, or Summary proto buffer strings are accepted")
        else:
            summary_pb = tf_summary_str_or_pb

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
                values.setdefault(history_image_key(
                    tag, namespace), []).append(image)
            else:
                values[history_image_key(value.tag, namespace)] = image
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
            values[namespaced_tag(value.tag, namespace)] = wandb.Histogram(
                np_histogram=np_histogram)
        elif value.tag == "_hparams_/session_start_info":
            if wandb.util.get_module("tensorboard.plugins.hparams"):
                from tensorboard.plugins.hparams import plugin_data_pb2
                plugin_data = plugin_data_pb2.HParamsPluginData()
                plugin_data.ParseFromString(
                    value.metadata.plugin_data.content)
                for key, param in six.iteritems(plugin_data.session_start_info.hparams):
                    if not wandb.run.config.get(key):
                        wandb.run.config[key] = param.number_value or param.string_value or param.bool_value
            else:
                wandb.termerror(
                    "Received hparams tf.summary, but could not import the hparams plugin from tensorboard")

    return values


__all__ = ["patch", "log", "tf_summary_to_dict", "history_image_key"]
