from .media import Media
import pathlib
import plotly.tools
import codecs
import json
from matplotlib.figure import Figure as MatplotlibFigure
from plotly.graph_objs import Figure as PlotlyFigure
from typing import Optional, Union


class Figure(Media):
    OBJ_TYPE = "plotly-file"
    RELATIVE_PATH = pathlib.Path("media") / "plotly"
    DEFAULT_FORMAT = "PLOTLY.JSON"

    _format: str
    _source_path: pathlib.Path
    _is_temp_path: bool
    _bind_path: Optional[pathlib.Path]
    _sha256: str
    _size: int

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
        self._source_path = self._generate_temp_path(suffix=f".{self._format}")
        self._is_temp_path = True
        with codecs.open(str(self._source_path), "w", encoding="utf-8") as f:
            json.dump(figure.to_json(), f)

        self._sha256 = self._compute_sha256(self._source_path)
        self._size = self._source_path.stat().st_size

    def from_matplotlib(self, mpl_figure: "MatplotlibFigure") -> None:

        figure = plotly.tools.mpl_to_plotly(mpl_figure)
        self.from_plotly(figure)  # type: ignore

    def to_json(self) -> dict:
        return {
            "_type": self.OBJ_TYPE,
            "sha256": self._sha256,
            "size": self._size,
            "path": str(self._bind_path),
        }
