__all__ = [
    "LinePlot",
    "ScatterPlot",
    "BarPlot",
    "ScalarChart",
    "CodeComparer",
    "ParallelCoordinatesPlot",
    "ParameterImportancePlot",
    "RunComparer",
    "MediaBrowser",
    "MarkdownPanel",
    "ConfusionMatrix",
    "DataFrames",
    "MultiRunTable",
    "Vega",
    "Vega2",
    "Vega3",
    "WeavePanel",
]

from .util import *
from .validators import *
from wandb.sdk.wandb_require_helpers import RequiresReportEditingMixin
from functools import wraps


def panel_grid_callback(f):
    @wraps(f)
    def wrapper(attr, panel, *args, **kwargs):
        panel.modified = True
        panel.panel_grid.panel_callback(panel)
        f(attr, panel, *args, **kwargs)

    return wrapper


def default_fget(attr, panel):
    if isinstance(attr.json_keys, str):
        return panel.config.get(attr.json_keys)
    elif isinstance(attr.json_keys, (list, tuple)):
        return [panel.config.get(k) for k in attr.json_keys]
    else:
        raise TypeError(
            f"Received unexpected type for json_keys ({type(attr.json_keys)!r}"
        )


@panel_grid_callback
def default_fset(attr, panel, value):
    if isinstance(attr.json_keys, str):
        panel.config[attr.json_keys] = value
    elif isinstance(attr.json_keys, (list, tuple)):
        for k, v in zip(attr.json_keys, value):
            panel.config[k] = v
    else:
        raise TypeError(
            f"Received unexpected type for json_keys ({type(attr.json_keys)!r}, {type(value)!r})"
        )


@panel_grid_callback
def default_fdel(attr, panel):
    if isinstance(attr.json_keys, str):
        del panel.config[attr.json_keys]
    elif isinstance(attr.json_keys, (list, tuple)):
        for k in attr.json_keys:
            del panel.config[k]
    else:
        raise TypeError(
            f"Received unexpected type for json_keys ({type(attr.json_keys)!r}"
        )


class PanelAttr(Attr):
    def __init__(
        self,
        json_keys: Union[str, List[str]],
        # typ: type = object(),
        fget: callable = default_fget,
        fset: callable = default_fset,
        fdel: callable = default_fdel,
        *args,
        **kwargs,
    ):
        super().__init__(fget, fset, fdel, *args, **kwargs)
        self.json_keys = json_keys
        # self.type = typ


class Panel(SubclassOnlyABC, RequiresReportEditingMixin):
    def __init__(self, panel_grid, spec=None, offset=0):
        self.panel_grid = panel_grid
        self._spec = spec or self._generate_default_panel_spec()
        self.offset = offset
        self.modified = False

    def __repr__(self):
        clas = self.__class__.__name__
        props = {
            k: getattr(self, k)
            for k, v in self.__class__.__dict__.items()
            if isinstance(v, PanelAttr)
        }
        settings = [f"{k}={v!r}" for k, v in props.items() if not is_none(v)]
        return "{}({})".format(clas, ", ".join(settings))

    def _generate_default_panel_spec(self):
        return {
            # "__id__": generate_name(),
            "viewType": self.view_type,
            "config": {},
            # "ref": None,
            # "layout": None,
        }

    @property
    def spec(self):
        return self._spec

    @property
    def config(self):
        return self._spec["config"]

    @property
    def layout(self):
        return self._spec["layout"]


class LinePlot(Panel):
    title = PanelAttr("chartTitle")
    x = PanelAttr("xAxis")
    y = PanelAttr("metrics")
    range_x = PanelAttr(["xAxisMin", "xAxisMax"])
    range_y = PanelAttr(["yAxisMin", "yAxisMax"])
    log_x = PanelAttr("xLogScale")
    log_y = PanelAttr("yLogScale")
    title_x = PanelAttr("xAxisTitle")
    title_y = PanelAttr("yAxisTitle")
    ignore_outliers = PanelAttr("ignoreOutliers")
    groupby = PanelAttr("groupBy")
    groupby_aggfunc = PanelAttr("groupAgg", validators=[options(AGGFUNCS)])
    groupby_rangefunc = PanelAttr("groupArea", validators=[options(RANGEFUNCS)])
    smoothing_factor = PanelAttr("smoothingWeight")
    smoothing_type = PanelAttr("smoothingType", validators=[options(SMOOTHING_TYPES)])
    smoothing_show_original = PanelAttr("showOriginalAfterSmoothing")
    max_runs_to_show = PanelAttr("limit")
    custom_expressions = PanelAttr("expressions")
    plot_type = PanelAttr("plotType", validators=[options(LINEPLOT_STYLES)])
    font_size = PanelAttr("fontSize", validators=[options(FONT_SIZES)])
    legend_position = PanelAttr(
        "legendPosition", validators=[options(LEGEND_POSITIONS)]
    )

    @property
    def view_type(self):
        return "Run History Line Plot"


class ScatterPlot(Panel):
    title = PanelAttr("chartTitle")
    x = PanelAttr("xAxis")
    y = PanelAttr("yAxis")
    z = PanelAttr("zAxis")
    color = PanelAttr("color")
    range_x = PanelAttr(["xAxisMin", "xAxisMax"])
    range_y = PanelAttr(["yAxisMin", "yAxisMax"])
    range_z = PanelAttr(["zAxisMin", "zAxisMax"])
    range_color = PanelAttr(["minColor", "maxColor"])
    log_x = PanelAttr("xAxisLogScale")
    log_y = PanelAttr("yAxisLogScale")
    log_z = PanelAttr("zAxisLogScale")
    running_ymin = PanelAttr("showMaxYAxisLine")
    running_ymax = PanelAttr("showMinYAxisLine")
    running_ymean = PanelAttr("showAvgYAxisLine")

    @property
    def view_type(self):
        return "Scatter Plot"


class BarPlot(Panel):
    title = PanelAttr("chartTitle")
    metrics = PanelAttr("metrics")
    vertical = PanelAttr("vertical")
    range_x = PanelAttr(["xAxisMin", "xAxisMax"])
    title_x = PanelAttr("xAxisTitle")
    title_y = PanelAttr("yAxisTitle")
    groupby = PanelAttr("groupBy")
    groupby_aggfunc = PanelAttr("groupAgg", validators=[options(AGGFUNCS)])
    groupby_rangefunc = PanelAttr("groupArea", validators=[options(RANGEFUNCS)])
    max_runs_to_show = PanelAttr("limit")
    max_bars_to_show = PanelAttr("barLimit")
    custom_expressions = PanelAttr("expressions")

    @property
    def view_type(self):
        return "Bar Chart"


def scalar_metric_fget(prop, panel):
    return panel.config.get(prop.json_keys, [None])[0]


@panel_grid_callback
def scalar_metric_fset(prop, panel, value):
    panel.config[prop.json_keys] = [value]


class ScalarChart(Panel):
    title = PanelAttr("chartTitle")
    metric = PanelAttr("metrics", scalar_metric_fget, scalar_metric_fset)
    groupby_aggfunc = PanelAttr("groupAgg", validators=[options(AGGFUNCS)])
    groupby_rangefunc = PanelAttr("groupArea", validators=[options(RANGEFUNCS)])
    custom_expressions = PanelAttr("expressions")

    @property
    def view_type(self):
        return "Scalar Chart"


class CodeComparer(Panel):
    diff = PanelAttr("diff")

    @property
    def view_type(self):
        return "Code Comparer"


class ParallelCoordinatesPlot(Panel):
    columns = PanelAttr("columns")
    title = PanelAttr("chartTitle")

    @property
    def view_type(self):
        return "Parallel Coordinates Plot"


class ParameterImportancePlot(Panel):
    with_respect_to = PanelAttr("targetKey")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.with_respect_to:
            self.with_respect_to = "_timestamp"

    @property
    def view_type(self):
        return "Parameter Importance"


class RunComparer(Panel):
    diff_only = PanelAttr("diffOnly", validators=[options("split", None)])

    @property
    def view_type(self):
        return "Run Comparer"


class MediaBrowser(Panel):
    num_columns = PanelAttr("columnCount")
    media_keys = PanelAttr("media_keys")

    @property
    def view_type(self):
        return "Media Browser"


class MarkdownPanel(Panel):
    markdown = PanelAttr("value")

    @property
    def view_type(self):
        return "Markdown Panel"


class ConfusionMatrix(Panel):
    @property
    def view_type(self):
        return "Confusion Matrix"


class DataFrames(Panel):
    @property
    def view_type(self):
        return "Data Frame Table"


class MultiRunTable(Panel):
    @property
    def view_type(self):
        return "Multi Run Table"


class Vega(Panel):
    @property
    def view_type(self):
        return "Vega"


class Vega2(Panel):
    @property
    def view_type(self):
        return "Vega2"


class Vega3(Panel):
    @property
    def view_type(self):
        return "Vega3"


class WeavePanel(Panel):
    @property
    def view_type(self):
        return "Weave"


panel_mapping = {
    # Panels with config
    "Run History Line Plot": LinePlot,
    "Scatter Plot": ScatterPlot,
    "Bar Chart": BarPlot,
    "Scalar Chart": ScalarChart,
    "Code Comparer": CodeComparer,
    "Parallel Coordinates Plot": ParallelCoordinatesPlot,
    "Parameter Importance": ParameterImportancePlot,
    "Run Comparer": RunComparer,
    "Media Browser": MediaBrowser,
    "Markdown Panel": MarkdownPanel,
    # Panels with no config
    "Confusion Matrix": ConfusionMatrix,
    "Data Frame Table": DataFrames,
    "Multi Run Table": MultiRunTable,
    "Vega": Vega,
    "Vega2": Vega2,
    "Vega3": Vega3,
    "Weave": WeavePanel,
}
