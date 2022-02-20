import json
import os
import re
from typing import cast, Optional, Sequence, TYPE_CHECKING, Union


import wandb
from wandb.util import (
    generate_id,
    get_full_typename,
    get_module,
    is_matplotlib_typename,
    is_numpy_array,
    is_pandas_data_frame,
    is_plotly_typename,
    mkdir_exists_ok,
)

from ._batched_media import _prune_max_seq, BatchableMedia
from ._media import Media
from ._wandb_value import WBValue

if TYPE_CHECKING:
    import matplotlib  # type: ignore
    import numpy as np  # type: ignore
    import pandas as pd  # type: ignore
    import plotly  # type: ignore

    from wandb.sdk.wandb_run import Run

    ValToJsonType = Union[
        dict,
        "WBValue",
        Sequence["WBValue"],
        "plotly.Figure",
        "matplotlib.artist.Artist",
        "pd.DataFrame",
        object,
    ]


_DATA_FRAMES_SUBDIR = os.path.join("media", "data_frames")


def _numpy_arrays_to_lists(
    payload: Union[dict, Sequence, "np.ndarray"]
) -> Union[Sequence, dict, str, int, float, bool]:
    # Casts all numpy arrays to lists so we don't convert them to histograms, primarily for Plotly

    if isinstance(payload, dict):
        res = {}
        for key, val in payload.items():
            res[key] = _numpy_arrays_to_lists(val)
        return res
    elif isinstance(payload, Sequence) and not isinstance(payload, str):
        return [_numpy_arrays_to_lists(v) for v in payload]
    elif is_numpy_array(payload):
        if TYPE_CHECKING:
            payload = cast("np.ndarray", payload)
        return [
            _numpy_arrays_to_lists(v)
            for v in (payload.tolist() if payload.ndim > 0 else [payload.tolist()])
        ]
    # Protects against logging non serializable objects
    elif isinstance(payload, Media):
        return str(payload.__class__.__name__)
    return payload


def _data_frame_to_json(
    df: "pd.DataFrame", run: "Run", key: str, step: Union[int, str]
) -> dict:
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
    pandas = get_module("pandas")
    fastparquet = get_module("fastparquet")
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

    data_frame_id = generate_id()

    df = df.copy()  # we don't want to modify the user's DataFrame instance.

    for _, series in df.items():
        for i, val in enumerate(series):
            if isinstance(val, WBValue):
                series.iat[i] = str(
                    json.dumps(val_to_json(run, key, val, namespace=step))
                )

    # We have to call this wandb_run_id because that name is treated specially by
    # our filtering code
    df["wandb_run_id"] = pandas.Series([str(run.id)] * len(df.index), index=df.index)

    df["wandb_data_frame_id"] = pandas.Series(
        [str(data_frame_id)] * len(df.index), index=df.index
    )
    frames_dir = os.path.join(run.dir, _DATA_FRAMES_SUBDIR)
    mkdir_exists_ok(frames_dir)
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


def history_dict_to_json(
    run: "Optional[Run]", payload: dict, step: Optional[int] = None
) -> dict:
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


# TODO: refine this
def val_to_json(
    run: "Optional[Run]",
    key: str,
    val: "ValToJsonType",
    namespace: Optional[Union[str, int]] = None,
) -> Union[Sequence, dict]:
    # Converts a wandb datatype to its JSON representation.
    if namespace is None:
        raise ValueError(
            "val_to_json must be called with a namespace(a step number, or 'summary') argument"
        )

    converted = val
    typename = get_full_typename(val)

    if is_pandas_data_frame(val):
        val = wandb.Table(dataframe=val)

    elif is_matplotlib_typename(typename) or is_plotly_typename(typename):
        val = wandb.data_types._plotly.Plotly.make_plot_media(val)
    elif isinstance(val, Sequence) and all(isinstance(v, WBValue) for v in val):
        assert run
        # This check will break down if Image/Audio/... have child classes.
        if (
            len(val)
            and isinstance(val[0], BatchableMedia)
            and all(isinstance(v, type(val[0])) for v in val)
        ):

            if TYPE_CHECKING:
                val = cast(Sequence["BatchableMedia"], val)

            items = _prune_max_seq(val)

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
        assert run
        if isinstance(val, Media) and not val.is_bound():
            if hasattr(val, "_log_type") and val._log_type in [
                "table",
                "partitioned-table",
                "joined-table",
            ]:

                # Special conditional to log tables as artifact entries as well.
                # I suspect we will generalize this as we transition to storing all
                # files in an artifact
                # we sanitize the key to meet the constraints defined in wandb_artifacts.py
                # in this case, leaving only alpha numerics or underscores.
                sanitized_key = re.sub(r"[^a-zA-Z0-9_]+", "", key)
                art = wandb.sdk.wandb_artifacts.Artifact(
                    "run-{}-{}".format(run.id, sanitized_key), "run_table"
                )
                art.add(val, key)
                run.log_artifact(art)

            # Partitioned tables and joined tables do not support being bound to runs.
            if not (
                hasattr(val, "_log_type")
                and val._log_type in ["partitioned-table", "joined-table"]
            ):
                val.bind_to_run(run, key, namespace)

        return val.to_json(run)

    return converted  # type: ignore
