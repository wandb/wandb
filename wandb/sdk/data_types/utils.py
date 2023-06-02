import logging
import os
import re
from typing import TYPE_CHECKING, Optional, Sequence, Union, cast

import wandb
from wandb import util

from .base_types.media import BatchableMedia, Media
from .base_types.wb_value import WBValue
from .image import _server_accepts_image_filenames
from .plotly import Plotly

if TYPE_CHECKING:  # pragma: no cover
    import matplotlib  # type: ignore
    import pandas as pd
    import plotly  # type: ignore

    from ..wandb_run import Run as LocalRun

    ValToJsonType = Union[
        dict,
        "WBValue",
        Sequence["WBValue"],
        "plotly.Figure",
        "matplotlib.artist.Artist",
        "pd.DataFrame",
        object,
    ]


def history_dict_to_json(
    run: Optional["LocalRun"],
    payload: dict,
    step: Optional[int] = None,
    ignore_copy_err: Optional[bool] = None,
) -> dict:
    # Converts a History row dict's elements so they're friendly for JSON serialization.

    if step is None:
        # We should be at the top level of the History row; assume this key is set.
        step = payload["_step"]

    # We use list here because we were still seeing cases of RuntimeError dict changed size
    for key in list(payload):
        val = payload[key]
        if isinstance(val, dict):
            payload[key] = history_dict_to_json(
                run, val, step=step, ignore_copy_err=ignore_copy_err
            )
        else:
            payload[key] = val_to_json(
                run, key, val, namespace=step, ignore_copy_err=ignore_copy_err
            )

    return payload


# TODO: refine this
def val_to_json(
    run: Optional["LocalRun"],
    key: str,
    val: "ValToJsonType",
    namespace: Optional[Union[str, int]] = None,
    ignore_copy_err: Optional[bool] = None,
) -> Union[Sequence, dict]:
    # Converts a wandb datatype to its JSON representation.
    if namespace is None:
        raise ValueError(
            "val_to_json must be called with a namespace(a step number, or 'summary') argument"
        )

    converted = val
    typename = util.get_full_typename(val)

    if util.is_pandas_data_frame(val):
        val = wandb.Table(dataframe=val)

    elif util.is_matplotlib_typename(typename) or util.is_plotly_typename(typename):
        val = Plotly.make_plot_media(val)
    elif (
        isinstance(val, Sequence)
        and not isinstance(val, str)
        and all(isinstance(v, WBValue) for v in val)
    ):
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

            if _server_accepts_image_filenames():
                for item in items:
                    item.bind_to_run(
                        run=run,
                        key=key,
                        step=namespace,
                        ignore_copy_err=ignore_copy_err,
                    )
            else:
                for i, item in enumerate(items):
                    item.bind_to_run(
                        run=run,
                        key=key,
                        step=namespace,
                        id_=i,
                        ignore_copy_err=ignore_copy_err,
                    )
                if run._attach_id and run._init_pid != os.getpid():
                    wandb.termwarn(
                        f"Attempting to log a sequence of {items[0].__class__.__name__} objects from multiple processes might result in data loss. Please upgrade your wandb server",
                        repeat=False,
                    )

            return items[0].seq_to_json(items, run, key, namespace)
        else:
            # TODO(adrian): Good idea to pass on the same key here? Maybe include
            # the array index?
            # There is a bug here: if this array contains two arrays of the same type of
            # anonymous media objects, their eventual names will collide.
            # This used to happen. The frontend doesn't handle heterogeneous arrays
            # raise ValueError(
            #    "Mixed media types in the same list aren't supported")
            return [
                val_to_json(
                    run, key, v, namespace=namespace, ignore_copy_err=ignore_copy_err
                )
                for v in val
            ]

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
                # we sanitize the key to meet the constraints
                # in this case, leaving only alpha numerics or underscores.
                sanitized_key = re.sub(r"[^a-zA-Z0-9_]+", "", key)
                art = wandb.Artifact(f"run-{run.id}-{sanitized_key}", "run_table")
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


def _prune_max_seq(seq: Sequence["BatchableMedia"]) -> Sequence["BatchableMedia"]:
    # If media type has a max respect it
    items = seq
    if hasattr(seq[0], "MAX_ITEMS") and seq[0].MAX_ITEMS < len(seq):
        logging.warning(
            "Only %i %s will be uploaded."
            % (seq[0].MAX_ITEMS, seq[0].__class__.__name__)
        )
        items = seq[: seq[0].MAX_ITEMS]
    return items
