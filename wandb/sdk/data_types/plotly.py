import codecs
import os
from typing import TYPE_CHECKING, Sequence, Type, Union

from wandb import util
from wandb.sdk.lib import runid

from ._private import MEDIA_TMP
from .base_types.media import Media, _numpy_arrays_to_lists
from .base_types.wb_value import WBValue
from .image import Image

if TYPE_CHECKING:  # pragma: no cover
    import matplotlib  # type: ignore
    import pandas as pd
    import plotly  # type: ignore

    from wandb.sdk.artifacts.artifact import Artifact

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


class Plotly(Media):
    """Wandb class for plotly plots.

    Arguments:
        val: matplotlib or plotly figure
    """

    _log_type = "plotly-file"

    @classmethod
    def make_plot_media(
        cls: Type["Plotly"], val: Union["plotly.Figure", "matplotlib.artist.Artist"]
    ) -> Union[Image, "Plotly"]:
        if util.is_matplotlib_typename(util.get_full_typename(val)):
            if util.matplotlib_contains_images(val):
                return Image(val)
            val = util.matplotlib_to_plotly(val)
        return cls(val)

    def __init__(self, val: Union["plotly.Figure", "matplotlib.artist.Artist"]):
        super().__init__()
        # First, check to see if the incoming `val` object is a plotfly figure
        if not util.is_plotly_figure_typename(util.get_full_typename(val)):
            # If it is not, but it is a matplotlib figure, then attempt to convert it to plotly
            if util.is_matplotlib_typename(util.get_full_typename(val)):
                if util.matplotlib_contains_images(val):
                    raise ValueError(
                        "Plotly does not currently support converting matplotlib figures containing images. \
                            You can convert the plot to a static image with `wandb.Image(plt)` "
                    )
                val = util.matplotlib_to_plotly(val)
            else:
                raise ValueError(
                    "Logged plots must be plotly figures, or matplotlib plots convertible to plotly via mpl_to_plotly"
                )

        tmp_path = os.path.join(MEDIA_TMP.name, runid.generate_id() + ".plotly.json")
        val = _numpy_arrays_to_lists(val.to_plotly_json())
        with codecs.open(tmp_path, "w", encoding="utf-8") as fp:
            util.json_dump_safer(val, fp)
        self._set_file(tmp_path, is_tmp=True, extension=".plotly.json")

    @classmethod
    def get_media_subdir(cls: Type["Plotly"]) -> str:
        return os.path.join("media", "plotly")

    def to_json(self, run_or_artifact: Union["LocalRun", "Artifact"]) -> dict:
        json_dict = super().to_json(run_or_artifact)
        json_dict["_type"] = self._log_type
        return json_dict
