import re
import time

import six
import wandb
from wandb.viz import create_custom_chart

# We have atleast the default namestep and a global step to track
# TODO: reset this structure on wandb.join
STEPS = {"": {"step": 0}, "global": {"step": 0, "last_log": None}}
# TODO(cling): Set these when tensorboard behavior is configured.
# We support rate limited logging by setting this to number of seconds,
# can be a floating point.
RATE_LIMIT_SECONDS = None
IGNORE_KINDS = ["graphs"]
tensor_util = wandb.util.get_module("tensorboard.util.tensor_util")


# prefer tensorboard, fallback to protobuf in tensorflow when tboard isn't available
pb = wandb.util.get_module(
    "tensorboard.compat.proto.summary_pb2"
) or wandb.util.get_module("tensorflow.core.framework.summary_pb2")
if pb:
    Summary = pb.Summary
else:
    Summary = None


def make_ndarray(tensor):
    if tensor_util:
        res = tensor_util.make_ndarray(tensor)
        # Tensorboard can log generic objects and we don't want to save them
        if res.dtype == "object":
            return None
        else:
            return res
    else:
        wandb.termwarn(
            "Can't convert tensor summary, upgrade tensorboard with `pip"
            " install tensorboard --upgrade`"
        )
        return None


def namespaced_tag(tag, namespace=""):
    if not namespace:
        return tag
    elif tag in namespace:
        # This happens with tensorboardX
        return namespace
    else:
        return namespace + "/" + tag


def history_image_key(key, namespace=""):
    """Converts invalid filesystem characters to _ for use in History keys.

    Unfortunately this means currently certain image keys will collide silently. We
    implement this mapping up here in the TensorFlow stuff rather than in the History
    stuff so that we don't have to store a mapping anywhere from the original keys to
    the safe ones.
    """
    return namespaced_tag(re.sub(r"[/\\]", "_", key), namespace)


def tf_summary_to_dict(tf_summary_str_or_pb, namespace=""):  # noqa: C901
    """Convert a Tensorboard Summary to a dictionary

    Accepts either a tensorflow.summary.Summary
    or one encoded as a string.
    """
    values = {}
    if hasattr(tf_summary_str_or_pb, "summary"):
        summary_pb = tf_summary_str_or_pb.summary
        values[namespaced_tag("global_step", namespace)] = tf_summary_str_or_pb.step
        values["_timestamp"] = tf_summary_str_or_pb.wall_time
    elif isinstance(tf_summary_str_or_pb, (str, bytes, bytearray)):
        summary_pb = Summary()
        summary_pb.ParseFromString(tf_summary_str_or_pb)
    else:
        summary_pb = tf_summary_str_or_pb

    if not hasattr(summary_pb, "value") or len(summary_pb.value) == 0:
        # Ignore these, caller is responsible for handling None
        return None

    def encode_images(img_strs, value):
        try:
            from PIL import Image
        except ImportError:
            wandb.termwarn(
                'Install pillow if you are logging images with Tensorboard. To install, run "pip install pillow".',
                repeat=False,
            )
            return

        if len(img_strs) == 0:
            return

        images = []
        for img_str in img_strs:
            # Supports gifs from TboardX
            if img_str.startswith(b"GIF"):
                images.append(wandb.Video(six.BytesIO(img_str), format="gif"))
            else:
                images.append(wandb.Image(Image.open(six.BytesIO(img_str))))
        tag_idx = value.tag.rsplit("/", 1)
        if len(tag_idx) > 1 and tag_idx[1].isdigit():
            tag, idx = tag_idx
            values.setdefault(history_image_key(tag, namespace), []).extend(images)
        else:
            values[history_image_key(value.tag, namespace)] = images

    for value in summary_pb.value:
        kind = value.WhichOneof("value")
        if kind in IGNORE_KINDS:
            continue
        if kind == "simple_value":
            values[namespaced_tag(value.tag, namespace)] = value.simple_value
        elif kind == "tensor":
            plugin_name = value.metadata.plugin_data.plugin_name
            if plugin_name == "scalars" or plugin_name == "":
                values[namespaced_tag(value.tag, namespace)] = make_ndarray(
                    value.tensor
                )
            elif plugin_name == "images":
                img_strs = value.tensor.string_val[2:]  # First two items are dims.
                encode_images(img_strs, value)
            elif plugin_name == "histograms":
                # https://github.com/tensorflow/tensorboard/blob/master/tensorboard/plugins/histogram/summary_v2.py#L15-L26
                ndarray = make_ndarray(value.tensor)
                shape = ndarray.shape
                counts = []
                bins = []
                if shape[0] > 1:
                    bins.append(ndarray[0][0])  # Add the left most edge
                    for v in ndarray:
                        counts.append(v[2])
                        bins.append(v[1])  # Add the right most edges
                elif shape[0] == 1:
                    counts = [ndarray[0][2]]
                    bins = ndarray[0][:2]
                if len(counts) > 0:
                    values[namespaced_tag(value.tag, namespace)] = wandb.Histogram(
                        np_histogram=(counts, bins)
                    )
            elif plugin_name == "pr_curves":
                pr_curve_data = make_ndarray(value.tensor)
                precision = pr_curve_data[-2, :].tolist()
                recall = pr_curve_data[-1, :].tolist()
                # TODO: (kdg) implement spec for showing additional info in tool tips
                # true_pos = pr_curve_data[1,:]
                # false_pos = pr_curve_data[2,:]
                # true_neg = pr_curve_data[1,:]
                # false_neg = pr_curve_data[1,:]
                # threshold = [1.0 / n for n in range(len(true_pos), 0, -1)]
                # min of each in case tensorboard ever changes their pr_curve
                # to allow for different length outputs
                data = []
                for i in range(min(len((precision)), len(recall))):
                    # drop additional threshold values if they exist
                    if precision[i] != 0 or recall[i] != 0:
                        data.append((recall[i], precision[i]))
                # sort data so custom chart looks the same as tb generated pr curve
                # ascending recall, descending precision for the same recall values
                data = sorted(data, key=lambda x: (x[0], -x[1]))
                data_table = wandb.Table(data=data, columns=["recall", "precision"])
                values[namespaced_tag(value.tag, namespace)] = create_custom_chart(
                    "wandb/line/v0",
                    data_table,
                    {"x": "recall", "y": "precision"},
                    {"title": "Precision v. Recall"},
                )
        elif kind == "image":
            img_str = value.image.encoded_image_string
            encode_images([img_str], value)
        # Coming soon...
        # elif kind == "audio":
        #     audio = wandb.Audio(
        #         six.BytesIO(value.audio.encoded_audio_string),
        #         sample_rate=value.audio.sample_rate,
        #         content_type=value.audio.content_type,
        #     )
        elif kind == "histo":
            tag = namespaced_tag(value.tag, namespace)
            if len(value.histo.bucket_limit) >= 3:
                first = (
                    value.histo.bucket_limit[0]
                    + value.histo.bucket_limit[0]  # noqa: W503
                    - value.histo.bucket_limit[1]  # noqa: W503
                )
                last = (
                    value.histo.bucket_limit[-2]
                    + value.histo.bucket_limit[-2]  # noqa: W503
                    - value.histo.bucket_limit[-3]  # noqa: W503
                )
                np_histogram = (
                    list(value.histo.bucket),
                    [first] + value.histo.bucket_limit[:-1] + [last],
                )
                try:
                    # TODO: we should just re-bin if there are too many buckets
                    values[tag] = wandb.Histogram(np_histogram=np_histogram)
                except ValueError:
                    wandb.termwarn(
                        'Not logging key "{}". '
                        "Histograms must have fewer than {} bins".format(
                            tag, wandb.Histogram.MAX_LENGTH
                        ),
                        repeat=False,
                    )
            else:
                # TODO: is there a case where we can render this?
                wandb.termwarn(
                    'Not logging key "{}".  Found a histogram with only 2 bins.'.format(
                        tag
                    ),
                    repeat=False,
                )
        # TODO(jhr): figure out how to share this between userspace and internal process or dont
        # elif value.tag == "_hparams_/session_start_info":
        #     if wandb.util.get_module("tensorboard.plugins.hparams"):
        #         from tensorboard.plugins.hparams import plugin_data_pb2
        #
        #         plugin_data = plugin_data_pb2.HParamsPluginData()        #
        #         plugin_data.ParseFromString(value.metadata.plugin_data.content)
        #         for key, param in six.iteritems(plugin_data.session_start_info.hparams):
        #             if not wandb.run.config.get(key):
        #                 wandb.run.config[key] = (
        #                     param.number_value or param.string_value or param.bool_value
        #                 )
        #     else:
        #         wandb.termerror(
        #             "Received hparams tf.summary, but could not import "
        #             "the hparams plugin from tensorboard"
        #         )
    return values


def reset_state():
    """Internal method for reseting state, called by wandb.join"""
    global STEPS
    STEPS = {"": {"step": 0}, "global": {"step": 0, "last_log": None}}


def log(tf_summary_str_or_pb, history=None, step=0, namespace="", **kwargs):
    """Logs a tfsummary to wandb

    Can accept a tf summary string or parsed event.  Will use wandb.run.history unless a
    history object is passed.  Can optionally namespace events.  Results are commited
    when step increases for this namespace.

    NOTE: This assumes that events being passed in are in chronological order
    """
    global STEPS
    global RATE_LIMIT
    history = history or wandb.run.history
    # To handle multiple global_steps, we keep track of them here instead
    # of the global log
    last_step = STEPS.get(namespace, {"step": 0})

    # Commit our existing data if this namespace increased its step
    commit = False
    if last_step["step"] < step:
        commit = True

    log_dict = tf_summary_to_dict(tf_summary_str_or_pb, namespace)
    if log_dict is None:
        # not an event, just return
        return

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
        if (
            RATE_LIMIT_SECONDS is None
            or timestamp - STEPS["global"]["last_log"] >= RATE_LIMIT_SECONDS
        ):
            history.add({}, **kwargs)
        STEPS["global"]["last_log"] = timestamp
    history._row_update(log_dict)
