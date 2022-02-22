import codecs
import os
from typing import TYPE_CHECKING, Union

from wandb.util import (
    generate_id,
    get_full_typename,
    is_matplotlib_typename,
    is_plotly_figure_typename,
    json_dump_safer,
    matplotlib_contains_images,
    matplotlib_to_plotly,
)

from ._image import Image
from ._media import Media
from .utils import _numpy_arrays_to_lists


if TYPE_CHECKING:
    import matplotlib  # type: ignore
    import plotly  # type: ignore
    from wandb_run import Run
    from wandb.sdk.wandb_artifacts import Artifact

    PlotlyFigureType = Union["plotly.Figure", "matplotlib.artist.Artist"]


class Plotly(Media):
    """
    Wandb class for plotly plots.

    Arguments:
        val: matplotlib or plotly figure
    """

    _log_type = "plotly-file"

    def __init__(self, figure: "PlotlyFigureType"):
        super().__init__()
        # First, check to see if the incoming `figure` object is a plotfly figure
        if not is_plotly_figure_typename(get_full_typename(figure)):
            # If it is not, but it is a matplotlib figure, then attempt to convert it to plotly
            if is_matplotlib_typename(get_full_typename(figure)):
                if matplotlib_contains_images(figure):
                    raise ValueError(
                        "Plotly does not currently support converting matplotlib figures containing images. \
                            You can convert the plot to a static image with `wandb.Image(plt)` "
                    )
                figure = matplotlib_to_plotly(figure)
            else:
                raise ValueError(
                    "Logged plots must be plotly figures, or matplotlib plots convertible to plotly via mpl_to_plotly"
                )

        path = os.path.join(self._MEDIA_TMP.name, generate_id() + ".plotly.json")
        plotly_json = _numpy_arrays_to_lists(figure.to_plotly_json())
        with codecs.open(path, "w", encoding="utf-8") as fp:
            json_dump_safer(plotly_json, fp)
        self._set_file(path, is_tmp=True, extension=".plotly.json")

    def to_json(self, run_or_artifact: Union["Run", "Artifact"]) -> dict:
        json_dict = super().to_json(run_or_artifact)
        json_dict["_type"] = self._log_type
        return json_dict

    @classmethod
    def get_media_subdir(cls: "Plotly") -> str:
        return os.path.join("media", "plotly")

    @classmethod
    def make_plot_media(
        cls: "Plotly", figure: "PlotlyFigureType"
    ) -> Union[Image, "Plotly"]:
        if is_matplotlib_typename(get_full_typename(figure)):
            if matplotlib_contains_images(figure):
                return Image(figure)
            figure = matplotlib_to_plotly(figure)
        return cls(figure)
