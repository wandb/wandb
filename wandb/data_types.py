"""
Wandb has special data types for logging rich visualizations.

All of the special data types are subclasses of WBValue. All of the data types
serialize to JSON, since that is what wandb uses to save the objects locally
and upload them to the W&B server.
"""

# This file is maintained so that users can access the data_types module
# as if it is a top-level module, rather than reaching into the sdk folder:
# `import wandb.data_types`
# `from wandb import data_types`
#
# After Py2 is dropped, we will pull all of this back to top level.

import sys

PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    from wandb.sdk.data_types import (
        WBValue,
        Histogram,
        Media,
        BatchableMedia,
        Table,
        Audio,
        Object3D,
        Molecule,
        Html,
        Video,
        Classes,
        JoinedTable,
        Image,
        JSONMetadata,
        BoundingBoxes2D,
        ImageMask,
        Plotly,
        Graph,
        Node,
        Edge,
        prune_max_seq,
        numpy_arrays_to_lists,
        val_to_json,
        history_dict_to_json,
    )
else:
    from wandb.sdk_py27.data_types import (
        WBValue,
        Histogram,
        Media,
        BatchableMedia,
        Table,
        Audio,
        Object3D,
        Molecule,
        Html,
        Video,
        Classes,
        JoinedTable,
        Image,
        JSONMetadata,
        BoundingBoxes2D,
        ImageMask,
        Plotly,
        Graph,
        Node,
        Edge,
        prune_max_seq,
        numpy_arrays_to_lists,
        val_to_json,
        history_dict_to_json,
    )

__all__ = [
    "WBValue",
    "Histogram",
    "Media",
    "BatchableMedia",
    "Table",
    "Audio",
    "Object3D",
    "Molecule",
    "Html",
    "Video",
    "Classes",
    "JoinedTable",
    "Image",
    "JSONMetadata",
    "BoundingBoxes2D",
    "ImageMask",
    "Plotly",
    "Graph",
    "Node",
    "Edge",
    "prune_max_seq",
    "numpy_arrays_to_lists",
    "val_to_json",
    "history_dict_to_json",
]
