import time
import os
import re
import six
import sys
import glob
import wandb

# Constants for patching tensorboard
TENSORBOARD_C_MODULE = "tensorflow.python.ops.gen_summary_ops"
TENSORBOARD_PYTORCH_MODULE = "tensorboard.summary.writer.event_file_writer"
TENSORBOARD_LEGACY_MODULE = "tensorflow.python.summary.writer.writer"

TENSORBOARDX_LOADED = "tensorboardX" in sys.modules
TENSORFLOW_LOADED = "tensorflow" in sys.modules
PYTORCH_TENSORBOARD = "torch" in sys.modules and wandb.util.get_module(
    "torch.utils.tensorboard") is not None

if not TENSORBOARDX_LOADED and not TENSORFLOW_LOADED and not PYTORCH_TENSORBOARD:
    # If we couldn't detect any libraries default to tensorboardX
    TENSORBOARDX_LOADED = wandb.util.get_module("tensorboardX") is not None

if TENSORBOARDX_LOADED:
    from tensorboardX.proto.summary_pb2 import Summary
else:
    pb = wandb.util.get_module("tensorboard.compat.proto.summary_pb2") or wandb.util.get_module(
        "tensorflow.summary")
    if pb:
        Summary = pb.Summary
    else:
        Summary = None


def tensorflow2_patched():
    return any((mod == TENSORBOARD_C_MODULE for mod, meth in wandb.patched["tensorboard"]))


def patch(save=True, tensorboardX=TENSORBOARDX_LOADED, pytorch=PYTORCH_TENSORBOARD):
    """Monkeypatches tensorboard or tensorboardX so that all events are logged to tfevents files and wandb.
    We save the tfevents files and graphs to wandb by default.

    Arguments:
        save, default: True - Passing False will skip storing tfevent files.
        tensorboardX, default: True if module can be imported - You can override this when calling patch
    """

    if len(wandb.patched["tensorboard"]) > 0:
        raise ValueError(
            "Tensorboard already patched, remove tensorboard=True from wandb.init or only call wandb.tensorboard.patch once.")
    elif Summary is None:
        raise ValueError(
            "Couldn't import tensorboard or tensorflow, ensure you have have tensorboard installed.")

    if tensorboardX:
        tensorboard_py_module = "tensorboardX.writer"
        if TENSORFLOW_LOADED:
            wandb.termlog(
                "Found tensorboardX and tensorflow, pass tensorboardX=False to patch regular tensorboard.")
    else:
        if wandb.util.get_module("tensorboard.summary.writer.event_file_writer") and pytorch:
            # If we haven't imported tensorflow, let's patch the python tensorboard writer
            tensorboard_py_module = TENSORBOARD_PYTORCH_MODULE
        else:
            # If we're using tensorflow >= 2.0 this patch won't be used, but we'll do it anyway
            tensorboard_py_module = TENSORBOARD_LEGACY_MODULE

    writers = set()
    writer = wandb.util.get_module(tensorboard_py_module)

    def add_event(orig_event):
        """TensorboardX, TensorFlow <= 1.14 patch, and Tensorboard Patch"""

        def _add_event(self, event):
            """Add event monkeypatch for python event writers"""
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
                    for path in glob.glob(os.path.join(log_dir, "*.pbtxt")):
                        if os.stat(path).st_mtime >= wandb.START_TIME:
                            wandb.save(path, base_path=log_dir)
                log(event, namespace=namespace, step=event.step)
            except Exception as e:
                wandb.termerror("Unable to log event %s" % e)
        return _add_event

    if writer:
        # This is for TensorboardX and PyTorch 1.1 python tensorboard logging
        writer.EventFileWriter.orig_add_event = writer.EventFileWriter.add_event
        writer.EventFileWriter.add_event = add_event(
            writer.EventFileWriter.add_event)
        wandb.patched["tensorboard"].append(
            [tensorboard_py_module, "EventFileWriter.add_event"])

    # This configures TensorFlow 2 style Tensorboard logging
    c_writer = wandb.util.get_module(TENSORBOARD_C_MODULE)
    if c_writer:
        old_csfw_func = c_writer.create_summary_file_writer

        def new_csfw_func(*args, **kwargs):
            """Tensorboard 2+ monkeypatch for streaming events from the filesystem"""
            logdir = kwargs['logdir'].numpy().decode("utf8") if hasattr(
                kwargs['logdir'], 'numpy') else kwargs['logdir']
            wandb.run.send_message(
                {"tensorboard": {"logdir": logdir, "save": save}})
            return old_csfw_func(*args, **kwargs)

        c_writer.orig_create_summary_file_writer = old_csfw_func
        c_writer.create_summary_file_writer = new_csfw_func
        wandb.patched["tensorboard"].append(
            [TENSORBOARD_C_MODULE, "create_summary_file_writer"])


def log(tf_summary_str, history=None, **kwargs):
    namespace = kwargs.get("namespace")
    if "namespace" in kwargs:
        del kwargs["namespace"]
    log_dict = tf_summary_to_dict(tf_summary_str, namespace)
    if history is None:
        wandb.log(log_dict, **kwargs)
    else:
        history.add(log_dict, **kwargs)


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
                values[history_image_key(value.tag, namespace)] = [image]
        # Coming soon...
        # elif kind == "audio":
        #    audio = wandb.Audio(six.BytesIO(value.audio.encoded_audio_string),
        #                        sample_rate=value.audio.sample_rate, content_type=value.audio.content_type)
        elif kind == "histo":
            tag = namespaced_tag(value.tag, namespace)
            if len(value.histo.bucket_limit) >= 3:
                first = value.histo.bucket_limit[0] + \
                    value.histo.bucket_limit[0] - value.histo.bucket_limit[1]
                last = value.histo.bucket_limit[-2] + \
                    value.histo.bucket_limit[-2] - value.histo.bucket_limit[-3]
                np_histogram = (list(value.histo.bucket), [
                    first] + value.histo.bucket_limit[:-1] + [last])
                try:
                    #TODO: we should just re-bin if there are too many buckets
                    values[tag] = wandb.Histogram(
                        np_histogram=np_histogram)
                except ValueError:
                    wandb.termwarn("Not logging key \"{}\".  Histograms must have fewer than {} bins".format(
                        tag, wandb.Histogram.MAX_LENGTH), repeat=False)
            else:
                #TODO: is there a case where we can render this?
                wandb.termwarn("Not logging key \"{}\".  Found a histogram with only 2 bins.".format(tag), repeat=False)
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


__all__ = ["patch", "log", "namespaced_tag", "tf_summary_to_dict", "history_image_key"]
