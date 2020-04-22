import time
import os
import re
import six
import sys
import glob
import wandb

for path in sys.path:
    if path.endswith(os.path.join("client", "wandb")):
        sys.path.remove(path)
    if path.endswith(os.path.join("site-packages", "wandb")):
        sys.path.remove(path)
if sys.modules.get("tensorboard"):
    # Remove tensorboard if it's us
    if hasattr(wandb.util.get_module("tensorboard"), "TENSORBOARD_C_MODULE"):
        del sys.modules["tensorboard"]
tensor_util = wandb.util.get_module("tensorboard.util.tensor_util")
def make_ndarray(tensor):
    if tensor_util:
        res = tensor_util.make_ndarray(tensor)
        # Tensorboard can log generic objects and we don't want to save them
        if res.dtype == "object":
            return None
        else:
            return res
    else:
        wandb.termwarn("Can't convert tensor summary, upgrade tensorboard with `pip install tensorboard --upgrade`")
        return None

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
            "Tensorboard already patched, remove sync_tensorboard=True from wandb.init or only call wandb.tensorboard.patch once.")
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
                        try:
                            name = self._ev_writer.FileName().decode("utf-8")
                        except AttributeError:
                            name = self._ev_writer.FileName()
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


# We have atleast the default namestep and a global step to track
# TODO: reset this structure on wandb.join
STEPS = {"": {"step": 0}, "global": {"step": 0, "last_log": None}}
# We support rate limited logging by settings this to number of seconds, can be a floating point
RATE_LIMIT_SECONDS = None
# To skip importing certain event types this can be set.  i.e. ["image", "histo"]
IGNORE_KINDS = []


def configure(ignore_kinds=None, rate_limit_seconds=None):
    """Configure tensorboard import to be rate_limited or ignore types of events.

    Example:
        # Don't log histograms to W&B and log events at most 1 once every 2 seconds
        wandb.tensorboard.configure(ignore_kinds=["histo"], rate_limit_seconds=2)
    """
    global IGNORE_KINDS
    global RATE_LIMIT_SECONDS
    IGNORE_KINDS = ignore_kinds or []
    RATE_LIMIT_SECONDS = rate_limit_seconds


def reset_state():
    """Internal method for reseting state, called by wandb.join"""
    global STEPS
    STEPS = {"": {"step": 0}, "global": {"step": 0, "last_log": None}}


def log(tf_summary_str_or_pb, history=None, step=0, namespace="", **kwargs):
    """Logs a tfsummary to wandb

    Can accept a tf summary string or parsed event.  Will use wandb.run.history unless a
    history object is passed.  Can optionally namespace events.  Results are commited when
    step increases for this namespace.  

    NOTE: This assumes that events being passed in are in chronological order
    """
    global STEPS
    global RATE_LIMIT
    history = history or wandb.run.history
    # To handle multiple global_steps, we keep track of them here instead of the global log
    last_step = STEPS.get(namespace, {"step": 0})

    # Commit our existing data if this namespace increased its step
    commit = False
    if last_step["step"] < step:
        commit = True

    log_dict = tf_summary_to_dict(tf_summary_str_or_pb, namespace)
    # Pass timestamp to history for loading historic data
    timestamp = log_dict.get("_timestamp", time.time())
    # Store our initial timestamp
    if STEPS["global"]["last_log"] is None:
        STEPS["global"]["last_log"] = timestamp
    # Rollup events that share the same step across namespaces
    if commit and step == STEPS["global"]["step"]:
        commit = False
    # Always add the biggest global_step key for non-default namespaces
    if step > STEPS["global"]["step"]:
        STEPS["global"]["step"] = step
    if namespace != "":
        log_dict["global_step"] = STEPS["global"]["step"]

    # Keep internal step counter
    STEPS[namespace] = {"step": step}

    if commit:
        # Only commit our data if we're below the rate limit or don't have one
        if RATE_LIMIT_SECONDS is None or timestamp - STEPS["global"]["last_log"] >= RATE_LIMIT_SECONDS:
            history.add({}, **kwargs)
        STEPS["global"]["last_log"] = timestamp
    history.update(log_dict)


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
        if kind in IGNORE_KINDS:
            continue
        if kind == "simple_value":
            values[namespaced_tag(value.tag, namespace)] = value.simple_value
        elif kind == "tensor":
            values[namespaced_tag(value.tag, namespace)] = make_ndarray(value.tensor)
        elif kind == "image":
            from PIL import Image
            img_str = value.image.encoded_image_string
            # Supports gifs from TboardX
            if img_str.startswith(b"GIF"):
                image = wandb.Video(six.BytesIO(img_str), format="gif")
            else:
                image = wandb.Image(Image.open(
                    six.BytesIO(img_str)))
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
