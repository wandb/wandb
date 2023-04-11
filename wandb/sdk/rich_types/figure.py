import codecs
import json
import pathlib
from typing import Union

import plotly.tools
from matplotlib.figure import Figure as MatplotlibFigure
from plotly.graph_objs import Figure as PlotlyFigure

from .media import Media


class Figure(Media):
    OBJ_TYPE = "plotly-file"
    RELATIVE_PATH = pathlib.Path("media") / "plotly"
    DEFAULT_FORMAT = "PLOTLY.JSON"

    _format: str

    def __init__(
        self,
        data_or_path: Union["PlotlyFigure", "MatplotlibFigure"],
    ) -> None:
        if isinstance(data_or_path, MatplotlibFigure):
            self.from_matplotlib(data_or_path)
        elif isinstance(data_or_path, PlotlyFigure):
            self.from_plotly(data_or_path)
        else:
            raise ValueError(
                "Plotly must be initialized with a plotly figure or matplotlib figure"
            )

        super().__init__()

    def from_plotly(self, figure: "PlotlyFigure") -> None:
        self._format = self.DEFAULT_FORMAT.lower()
        with self.manager.save(suffix=f".{self._format}") as path:
            with codecs.open(str(path), "w", encoding="utf-8") as f:
                json.dump(figure.to_json(), f)

    def from_matplotlib(self, mpl_figure: "MatplotlibFigure") -> None:
        figure = plotly.tools.mpl_to_plotly(mpl_figure)
        self.from_plotly(figure)  # type: ignore

    def to_json(self) -> dict:
        return {
            "_type": self.OBJ_TYPE,
            **super().to_json(),
        }
