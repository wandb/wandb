import codecs
import os
from typing import Type, TYPE_CHECKING, Union

from _image import Image
from _media import Media
from utils import _numpy_arrays_to_lists

from wandb.util import (
    get_full_typename,
    generate_id,
    is_matplotlib_typename,
    is_plotly_figure_typename,
    json_dump_safer,
    matplotlib_contains_images,
    matplotlib_to_plotly,
)

if TYPE_CHECKING:
    import matplotlib  # type: ignore
    import plotly  # type: ignore
    from wandb_run import Run
    from wandb.sdk.wandb_artifacts import Artifact


class Plotly(Media):
    """
    Wandb class for plotly plots.

    Arguments:
        val: matplotlib or plotly figure
    """

    _log_type = "plotly-file"

    @classmethod
    def make_plot_media(
        cls: Type["Plotly"], val: Union["plotly.Figure", "matplotlib.artist.Artist"]
    ) -> Union[Image, "Plotly"]:
        if is_matplotlib_typename(get_full_typename(val)):
            if matplotlib_contains_images(val):
                return Image(val)
            val = matplotlib_to_plotly(val)
        return cls(val)

    def __init__(self, val: Union["plotly.Figure", "matplotlib.artist.Artist"]):
        super().__init__()
        # First, check to see if the incoming `val` object is a plotfly figure
        if not is_plotly_figure_typename(get_full_typename(val)):
            # If it is not, but it is a matplotlib figure, then attempt to convert it to plotly
            if is_matplotlib_typename(get_full_typename(val)):
                if matplotlib_contains_images(val):
                    raise ValueError(
                        "Plotly does not currently support converting matplotlib figures containing images. \
                            You can convert the plot to a static image with `wandb.Image(plt)` "
                    )
                val = matplotlib_to_plotly(val)
            else:
                raise ValueError(
                    "Logged plots must be plotly figures, or matplotlib plots convertible to plotly via mpl_to_plotly"
                )

        tmp_path = os.path.join(self._MEDIA_TMP.name, generate_id() + ".plotly.json")
        val = _numpy_arrays_to_lists(val.to_plotly_json())
        with codecs.open(tmp_path, "w", encoding="utf-8") as fp:
            json_dump_safer(val, fp)
        self._set_file(tmp_path, is_tmp=True, extension=".plotly.json")

    @classmethod
    def get_media_subdir(cls: Type["Plotly"]) -> str:
        return os.path.join("media", "plotly")

    def to_json(self, run_or_artifact: Union["Run", "Artifact"]) -> dict:
        json_dict = super().to_json(run_or_artifact)
        json_dict["_type"] = self._log_type
        return json_dict
