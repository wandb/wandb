import io
import re
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import wandb
import wandb.util
from wandb.sdk.lib import telemetry
from wandb.viz import custom_chart

if TYPE_CHECKING:
    import numpy as np

    from wandb.sdk.internal.tb_watcher import TBHistory

# We have at least the default namestep and a global step to track
# TODO: reset this structure on wandb.finish
STEPS: Dict[str, Dict[str, Any]] = {
    "": {"step": 0},
    "global": {"step": 0, "last_log": None},
}
# TODO(cling): Set these when tensorboard behavior is configured.
# We support rate limited logging by setting this to number of seconds,
# can be a floating point.
RATE_LIMIT_SECONDS: Optional[Union[float, int]] = None
IGNORE_KINDS = ["graphs"]
tensor_util = wandb.util.get_module("tensorboard.util.tensor_util")


# prefer tensorboard, fallback to protobuf in tensorflow when tboard isn't available
pb = wandb.util.get_module(
    "tensorboard.compat.proto.summary_pb2"
) or wandb.util.get_module("tensorflow.core.framework.summary_pb2")

Summary = pb.Summary if pb else None


def make_ndarray(tensor: Any) -> Optional["np.ndarray"]:
    if tensor_util:
        res = tensor_util.make_ndarray(tensor)
        # Tensorboard can log generic objects, and we don't want to save them
        if res.dtype == "object":
            return None
        else:
            return res  # type: ignore
    else:
        wandb.termwarn(
            "Can't convert tensor summary, upgrade tensorboard with `pip"
            " install tensorboard --upgrade`"
        )
        return None


def namespaced_tag(tag: str, namespace: str = "") -> str:
    if not namespace:
        return tag
    elif tag in namespace:
        # This happens with tensorboardX
        return namespace
    else:
        return namespace + "/" + tag


def history_image_key(key: str, namespace: str = "") -> str:
    """Convert invalid filesystem characters to _ for use in History keys.

    Unfortunately this means currently certain image keys will collide silently. We
    implement this mapping up here in the TensorFlow stuff rather than in the History
    stuff so that we don't have to store a mapping anywhere from the original keys to
    the safe ones.
    """
    return namespaced_tag(re.sub(r"[/\\]", "_", key), namespace)


def tf_summary_to_dict(  # noqa: C901
    tf_summary_str_or_pb: Any, namespace: str = ""
) -> Optional[Dict[str, Any]]:
    """Convert a Tensorboard Summary to a dictionary.

    Accepts a tensorflow.summary.Summary, one encoded as a string,
    or a list of such encoded as strings.
    """
    values = {}
    if hasattr(tf_summary_str_or_pb, "summary"):
        summary_pb = tf_summary_str_or_pb.summary
        values[namespaced_tag("global_step", namespace)] = tf_summary_str_or_pb.step
        values["_timestamp"] = tf_summary_str_or_pb.wall_time
    elif isinstance(tf_summary_str_or_pb, (str, bytes, bytearray)):
        summary_pb = Summary()
        summary_pb.ParseFromString(tf_summary_str_or_pb)
    elif hasattr(tf_summary_str_or_pb, "__iter__"):
        summary_pb = [Summary() for _ in range(len(tf_summary_str_or_pb))]
        for i, summary in enumerate(tf_summary_str_or_pb):
            summary_pb[i].ParseFromString(summary)
            if i > 0:
                summary_pb[0].MergeFrom(summary_pb[i])
        summary_pb = summary_pb[0]
    else:
        summary_pb = tf_summary_str_or_pb

    if not hasattr(summary_pb, "value") or len(summary_pb.value) == 0:
        # Ignore these, caller is responsible for handling None
        return None

    def encode_images(_img_strs: List[bytes], _value: Any) -> None:
        try:
            from PIL import Image
        except ImportError:
            wandb.termwarn(
                "Install pillow if you are logging images with Tensorboard. "
                "To install, run `pip install pillow`.",
                repeat=False,
            )
            return None

        if len(_img_strs) == 0:
            return None

        images: List[Union[wandb.Video, wandb.Image]] = []
        for _img_str in _img_strs:
            # Supports gifs from TensorboardX
            if _img_str.startswith(b"GIF"):
                images.append(wandb.Video(io.BytesIO(_img_str), format="gif"))
            else:
                images.append(wandb.Image(Image.open(io.BytesIO(_img_str))))
        tag_idx = _value.tag.rsplit("/", 1)
        if len(tag_idx) > 1 and tag_idx[1].isdigit():
            tag, idx = tag_idx
            values.setdefault(history_image_key(tag, namespace), []).extend(images)
        else:
            values[history_image_key(_value.tag, namespace)] = images

        return None

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
                if ndarray is None:
                    continue
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
                    try:
                        # TODO: we should just re-bin if there are too many buckets
                        values[namespaced_tag(value.tag, namespace)] = wandb.Histogram(
                            np_histogram=(counts, bins)  # type: ignore
                        )
                    except ValueError:
                        wandb.termwarn(
                            'Not logging key "{}". '
                            "Histograms must have fewer than {} bins".format(
                                namespaced_tag(value.tag, namespace),
                                wandb.Histogram.MAX_LENGTH,
                            ),
                            repeat=False,
                        )
            elif plugin_name == "pr_curves":
                pr_curve_data = make_ndarray(value.tensor)
                if pr_curve_data is None:
                    continue
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
                for i in range(min(len(precision), len(recall))):
                    # drop additional threshold values if they exist
                    if precision[i] != 0 or recall[i] != 0:
                        data.append((recall[i], precision[i]))
                # sort data so custom chart looks the same as tb generated pr curve
                # ascending recall, descending precision for the same recall values
                data = sorted(data, key=lambda x: (x[0], -x[1]))
                data_table = wandb.Table(data=data, columns=["recall", "precision"])
                name = namespaced_tag(value.tag, namespace)

                values[name] = custom_chart(
                    "wandb/line/v0",
                    data_table,
                    {"x": "recall", "y": "precision"},
                    {"title": f"{name} Precision v. Recall"},
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
                    + value.histo.bucket_limit[0]
                    - value.histo.bucket_limit[1]
                )
                last = (
                    value.histo.bucket_limit[-2]
                    + value.histo.bucket_limit[-2]
                    - value.histo.bucket_limit[-3]
                )
                np_histogram = (
                    list(value.histo.bucket),
                    [first] + value.histo.bucket_limit[:-1] + [last],
                )
                try:
                    # TODO: we should just re-bin if there are too many buckets
                    values[tag] = wandb.Histogram(np_histogram=np_histogram)  # type: ignore
                except ValueError:
                    wandb.termwarn(
                        f"Not logging key {tag!r}. "
                        f"Histograms must have fewer than {wandb.Histogram.MAX_LENGTH} bins",
                        repeat=False,
                    )
            else:
                # TODO: is there a case where we can render this?
                wandb.termwarn(
                    f"Not logging key {tag!r}. Found a histogram with only 2 bins.",
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


def reset_state() -> None:
    """Internal method for resetting state, called by wandb.finish()."""
    global STEPS
    STEPS = {"": {"step": 0}, "global": {"step": 0, "last_log": None}}


def _log(
    tf_summary_str_or_pb: Any,
    history: Optional["TBHistory"] = None,
    step: int = 0,
    namespace: str = "",
    **kwargs: Any,
) -> None:
    """Logs a tfsummary to wandb.

    Can accept a tf summary string or parsed event.  Will use wandb.run.history unless a
    history object is passed.  Can optionally namespace events.  Results are committed
    when step increases for this namespace.

    NOTE: This assumes that events being passed in are in chronological order
    """
    global STEPS
    global RATE_LIMIT_SECONDS
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
            if history is None:
                if wandb.run is not None:
                    wandb.run._log({})
            else:
                history.add({})

        STEPS["global"]["last_log"] = timestamp

    if history is None:
        if wandb.run is not None:
            wandb.run._log(log_dict, commit=False)
    else:
        history._row_update(log_dict)


def log(tf_summary_str_or_pb: Any, step: int = 0, namespace: str = "") -> None:
    if wandb.run is None:
        raise wandb.Error(
            "You must call `wandb.init()` before calling `wandb.tensorflow.log`"
        )

    with telemetry.context() as tel:
        tel.feature.tensorboard_log = True

    _log(tf_summary_str_or_pb, namespace=namespace, step=step)
