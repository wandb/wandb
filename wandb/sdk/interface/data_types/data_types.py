# -*- coding: utf-8 -*-

"""
Wandb has special data types for logging rich visualizations.

All of the special data types are subclasses of WBValue. All of the data types
serialize to JSON, since that is what wandb uses to save the objects locally
and upload them to the W&B server.
"""

from __future__ import print_function

import hashlib
import itertools
import json
import pprint
import shutil
from six.moves import queue
import warnings

import numbers
import collections
import os
import io
import logging
import six
import wandb
import uuid
import json
import codecs
import tempfile
import sys
import base64
import binascii
from wandb import util
from wandb.util import has_num
from wandb.compat import tempfile


def _safe_sdk_import():
    """Safely imports sdks respecting python version"""

    PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
    if PY3:
        from wandb.sdk import wandb_run
        from wandb.sdk import wandb_artifacts
    else:
        from wandb.sdk_py27 import wandb_run
        from wandb.sdk_py27 import wandb_artifacts

    return wandb_run, wandb_artifacts


# Get rid of cleanup warnings in Python 2.7.
warnings.filterwarnings(
    "ignore", "Implicitly cleaning up", RuntimeWarning, "wandb.compat.tempfile"
)

# Staging directory so we can encode raw data into files, then hash them before
# we put them into the Run directory to be uploaded.
MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")

DATA_FRAMES_SUBDIR = os.path.join("media", "data_frames")


# cling below
_glob_datatypes_callback = None


def _datatypes_set_callback(cb):
    global _glob_datatypes_callback
    _glob_datatypes_callback = cb


def _datatypes_callback(fname):
    if _glob_datatypes_callback:
        _glob_datatypes_callback(fname)


# cling above


def wb_filename(key, step, id, extension):
    return "{}_{}_{}{}".format(key, step, id, extension)


def is_numpy_array(data):
    np = util.get_module(
        "numpy", required="Logging raw point cloud data requires numpy"
    )
    return isinstance(data, np.ndarray)


def nest(thing):
    # Use tensorflows nest function if available, otherwise just wrap object in an array"""

    tfutil = util.get_module("tensorflow.python.util")
    if tfutil:
        return tfutil.nest.flatten(thing)
    else:
        return [thing]


def history_dict_to_json(run, payload, step=None):
    # Converts a History row dict's elements so they're friendly for JSON serialization.

    if step is None:
        # We should be at the top level of the History row; assume this key is set.
        step = payload["_step"]

    # We use list here because we were still seeing cases of RuntimeError dict changed size
    for key in list(payload):
        val = payload[key]
        if isinstance(val, dict):
            payload[key] = history_dict_to_json(run, val, step=step)
        else:
            payload[key] = val_to_json(run, key, val, namespace=step)

    return payload


def numpy_arrays_to_lists(payload):
    # Casts all numpy arrays to lists so we don't convert them to histograms, primarily for Plotly

    if isinstance(payload, dict):
        res = {}
        for key, val in six.iteritems(payload):
            res[key] = numpy_arrays_to_lists(val)
        return res
    elif isinstance(payload, collections.Sequence) and not isinstance(
        payload, six.string_types
    ):
        return [numpy_arrays_to_lists(v) for v in payload]
    elif util.is_numpy_array(payload):
        return [numpy_arrays_to_lists(v) for v in payload.tolist()]

    return payload


def prune_max_seq(seq):
    # If media type has a max respect it
    items = seq
    if hasattr(seq[0], "MAX_ITEMS") and seq[0].MAX_ITEMS < len(seq):
        logging.warning(
            "Only %i %s will be uploaded."
            % (seq[0].MAX_ITEMS, seq[0].__class__.__name__)
        )
        items = seq[: seq[0].MAX_ITEMS]
    return items


def val_to_json(run, key, val, namespace=None):
    # Converts a wandb datatype to its JSON representation.
    if namespace == None:
        raise ValueError(
            "val_to_json must be called with a namespace(a step number, or 'summary') argument"
        )

    converted = val
    typename = util.get_full_typename(val)

    if util.is_pandas_data_frame(val):
        assert namespace == "summary", "We don't yet support DataFrames in History."
        return data_frame_to_json(val, run, key, namespace)
    elif util.is_matplotlib_typename(typename) or util.is_plotly_typename(typename):
        val = Plotly.make_plot_media(val)
    elif isinstance(val, collections.Sequence) and all(
        isinstance(v, WBValue) for v in val
    ):
        # This check will break down if Image/Audio/... have child classes.
        if (
            len(val)
            and isinstance(val[0], BatchableMedia)
            and all(isinstance(v, type(val[0])) for v in val)
        ):
            items = prune_max_seq(val)

            for i, item in enumerate(items):
                item.bind_to_run(run, key, namespace, id_=i)

            return items[0].seq_to_json(items, run, key, namespace)
        else:
            # TODO(adrian): Good idea to pass on the same key here? Maybe include
            # the array index?
            # There is a bug here: if this array contains two arrays of the same type of
            # anonymous media objects, their eventual names will collide.
            # This used to happen. The frontend doesn't handle heterogenous arrays
            # raise ValueError(
            #    "Mixed media types in the same list aren't supported")
            return [val_to_json(run, key, v, namespace=namespace) for v in val]

    if isinstance(val, WBValue):
        if isinstance(val, Media) and not val.is_bound():
            val.bind_to_run(run, key, namespace)
        return val.to_json(run)

    return converted


def data_frame_to_json(df, run, key, step):
    """!NODOC Encode a Pandas DataFrame into the JSON/backend format.

    Writes the data to a file and returns a dictionary that we use to represent
    it in `Summary`'s.

    Arguments:
        df (pandas.DataFrame): The DataFrame. Must not have columns named
            "wandb_run_id" or "wandb_data_frame_id". They will be added to the
            DataFrame here.
        run (wandb_run.Run): The Run the DataFrame is associated with. We need
            this because the information we store on the DataFrame is derived
            from the Run it's in.
        key (str): Name of the DataFrame, ie. the summary key path in which it's
            stored. This is for convenience, so people exploring the
            directory tree can have some idea of what is in the Parquet files.
        step: History step or "summary".

    Returns:
        A dict representing the DataFrame that we can store in summaries or
        histories. This is the format:
        {
            '_type': 'data-frame',
                # Magic field that indicates that this object is a data frame as
                # opposed to a normal dictionary or anything else.
            'id': 'asdf',
                # ID for the data frame that is unique to this Run.
            'format': 'parquet',
                # The file format in which the data frame is stored. Currently can
                # only be Parquet.
            'project': 'wfeas',
                # (Current) name of the project that this Run is in. It'd be
                # better to store the project's ID because we know it'll never
                # change but we don't have that here. We store this just in
                # case because we use the project name in identifiers on the
                # back end.
            'path': 'media/data_frames/sdlk.parquet',
                # Path to the Parquet file in the Run directory.
        }
    """
    pandas = util.get_module("pandas")
    fastparquet = util.get_module("fastparquet")
    missing_reqs = []
    if not pandas:
        missing_reqs.append("pandas")
    if not fastparquet:
        missing_reqs.append("fastparquet")
    if len(missing_reqs) > 0:
        raise wandb.Error(
            "Failed to save data frame. Please run 'pip install %s'"
            % " ".join(missing_reqs)
        )

    data_frame_id = util.generate_id()

    df = df.copy()  # we don't want to modify the user's DataFrame instance.

    for col_name, series in df.items():
        for i, val in enumerate(series):
            if isinstance(val, WBValue):
                series.iat[i] = six.text_type(
                    json.dumps(val_to_json(run, key, val, namespace=step))
                )

    # We have to call this wandb_run_id because that name is treated specially by
    # our filtering code
    df["wandb_run_id"] = pandas.Series(
        [six.text_type(run.id)] * len(df.index), index=df.index
    )

    df["wandb_data_frame_id"] = pandas.Series(
        [six.text_type(data_frame_id)] * len(df.index), index=df.index
    )
    frames_dir = os.path.join(run.dir, DATA_FRAMES_SUBDIR)
    util.mkdir_exists_ok(frames_dir)
    path = os.path.join(frames_dir, "{}-{}.parquet".format(key, data_frame_id))
    fastparquet.write(path, df)

    return {
        "id": data_frame_id,
        "_type": "data-frame",
        "format": "parquet",
        "project": run.project_name(),  # we don't have the project ID here
        "entity": run.entity,
        "run": run.id,
        "path": path,
    }
