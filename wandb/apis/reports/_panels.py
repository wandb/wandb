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
    # "DataFrames",
    # "MultiRunTable",
    # "Vega",
    # "Vega2",
    # "Vega3",
    # "WeavePanel",
]

from functools import wraps
from typing import List, Union
from dataclasses import dataclass, field

from wandb.sdk.wandb_require_helpers import RequiresReportEditingMixin

from ._panel_helpers import LineKey, RGBA
from .util import Attr, attr, generate_name, is_none, SubclassOnlyABC, UNDEFINED_TYPE
from .validators import (
    AGGFUNCS,
    between,
    CODE_COMPARE_DIFF,
    elem_types,
    FONT_SIZES,
    LEGEND_POSITIONS,
    length,
    LINEPLOT_STYLES,
    MARKS,
    one_of,
    RANGEFUNCS,
    SMOOTHING_TYPES,
    type_validate,
)


def panel_grid_callback(f):
    @wraps(f)
    def wrapper(attr, panel, *args, **kwargs):
        panel.modified = True
        if hasattr(panel, "disable_callback") and not panel.disable_callback:
            # if not panel.disable_callback:
            panel.panel_grid.panel_callback(panel)
        f(attr, panel, *args, **kwargs)

    return wrapper


def default_fget(attr, panel, default=None):
    if isinstance(attr.json_keys, str):
        return panel.config.get(attr.json_keys, default)
    elif isinstance(attr.json_keys, (list, tuple)):
        return [panel.config.get(k, default) for k in attr.json_keys]
    else:
        raise TypeError(
            f"Received unexpected type for json_keys ({type(attr.json_keys)!r}"
        )


@panel_grid_callback
def default_fset(attr, panel, value):
    if isinstance(attr.json_keys, str):
        panel.config[attr.json_keys] = value
    elif isinstance(attr.json_keys, (list, tuple)):
        if isinstance(value, type(None)):
            value = [None] * len(attr.json_keys)
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
    """
    Attr that reads from and writes to panel config
    """

    def __init__(
        self,
        json_keys: Union[str, List[str]],
        attr_type=UNDEFINED_TYPE,
        default=None,
        fget: callable = default_fget,
        fset: callable = default_fset,
        # fdel: callable = default_fdel,
        *args,
        **kwargs,
    ):
        super().__init__(attr_type, default, fget, fset, *args, **kwargs)
        self.json_keys = json_keys


def panel_attr(*args, repr=True, **kwargs):
    return field(default=PanelAttr(*args, **kwargs), repr=repr)


def _generate_default_panel_spec():
    return {
        "__id__": generate_name(),
        "viewType": None,
        "config": {},
        # "ref": None,
        "layout": {"x": 0, "y": 0, "w": 8, "h": 6},
    }


@dataclass
class Panel(SubclassOnlyABC, RequiresReportEditingMixin):
    panel_grid: ... = attr()
    _spec: ... = attr(dict, default=_generate_default_panel_spec(), repr=False)
    offset: ... = attr(int, default=0, repr=False)

    def __post_init__(self):
        self._spec["viewType"] = self.view_type
        # if self._spec is None:
        #     self._spec = self._generate_default_panel_spec()
        self.disable_callback = True if self.panel_grid is None else False
        self.modified = False

    # panel_grid: ... = Attr()  # of type PanelGrid
    # _spec: ... = Attr()
    # offset: ... = Attr(int)

    # def __init__(self, panel_grid=None, spec=None, offset=0):
    #     # self.panel_grid = panel_grid
    #     self._spec = spec or self._generate_default_panel_spec()
    #     self.offset = offset
    #     self.modified = False
    #     self.disable_callbacks = True if self.panel_grid is None else False

    def __repr__(self):
        clas = self.__class__.__name__
        props = {
            k: getattr(self, k)
            for k, v in self.__class__.__dict__.items()
            if isinstance(v, PanelAttr)
        }
        settings = [f"{k}={v!r}" for k, v in props.items() if not is_none(v)]
        return "{}({})".format(clas, ", ".join(settings))

    # def _generate_default_panel_spec(self):
    #     return {
    #         "__id__": generate_name(),
    #         "viewType": self.view_type,
    #         "config": {},
    #         # "ref": None,
    #         "layout": {"x": 0, "y": 0, "w": 8, "h": 6},
    #     }

    @property
    def view_type(self):
        return "NOPE"

    @property
    def spec(self):
        return self._spec

    @property
    def config(self):
        return self._spec["config"]

    @property
    def layout(self):
        return self._spec["layout"]

    @layout.setter
    def layout(self, new_layout):

        try:
            params = new_layout.items()
        except AttributeError:
            raise TypeError(f"Layout must be a dict (got {type(new_layout)!r})")

        required_keys = {"x", "y", "w", "h"}
        given_keys = set(new_layout.keys())

        if required_keys != given_keys:
            missing_keys = required_keys - given_keys
            extra_keys = given_keys - required_keys
            raise ValueError(
                f"Layout must be a dict with keys {required_keys} (missing keys: {missing_keys!r}, extraneous_keys: {extra_keys!r})"
            )

        for k, v in params:
            if not isinstance(v, int):
                raise TypeError(
                    f"Layout dimensions must be of {int} (got {k}={type(v)!r})"
                )
        self._spec["layout"] = new_layout


def line_override_get(attr, panel, default={}):
    titles = panel.config.get(attr.json_keys, default)
    return {LineKey(k): v for k, v in titles.items()} if titles is not None else None


def line_override_set(attr, panel, value):
    titles = (
        {linekey.key: v for linekey, v in value.items()} if value is not None else None
    )
    panel.config[attr.json_keys] = titles


def line_color_override_get(attr, panel, default={}):
    colors = panel.config.get(attr.json_keys, default)
    return (
        {LineKey(k): RGBA.from_json(v) for k, v in colors.items()}
        if colors is not None
        else None
    )


def line_color_override_set(attr, panel, colors):
    colors = (
        {linekey.key: v.spec for linekey, v in colors.items()}
        if colors is not None
        else None
    )
    panel.config[attr.json_keys] = colors


@dataclass
class LinePlot(Panel):
    title: ... = panel_attr("chartTitle", str)
    x: ... = panel_attr("xAxis", str)
    y: ... = panel_attr("metrics", list)
    range_x: ... = panel_attr(
        ["xAxisMin", "xAxisMax"],
        (list, tuple),
        validators=[length(2), elem_types((int, float))],
    )
    range_y: ... = panel_attr(
        ["yAxisMin", "yAxisMax"],
        (list, tuple),
        validators=[length(2), elem_types((int, float))],
    )
    log_x: ... = panel_attr("xLogScale", bool)
    log_y: ... = panel_attr("yLogScale", bool)
    title_x: ... = panel_attr("xAxisTitle", str)
    title_y: ... = panel_attr("yAxisTitle", str)
    ignore_outliers: ... = panel_attr("ignoreOutliers", bool)
    groupby: ... = panel_attr("groupBy", str)
    groupby_aggfunc: ... = panel_attr("groupAgg", validators=[one_of(AGGFUNCS)])
    groupby_rangefunc: ... = panel_attr("groupArea", validators=[one_of(RANGEFUNCS)])
    smoothing_factor: ... = panel_attr("smoothingWeight", float)
    smoothing_type: ... = panel_attr(
        "smoothingType", validators=[one_of(SMOOTHING_TYPES)]
    )
    smoothing_show_original: ... = panel_attr("showOriginalAfterSmoothing", bool)
    max_runs_to_show: ... = panel_attr("limit", int)
    custom_expressions: ... = panel_attr("expressions", str)
    plot_type: ... = panel_attr("plotType", validators=[one_of(LINEPLOT_STYLES)])
    font_size: ... = panel_attr("fontSize", validators=[one_of(FONT_SIZES)])
    legend_position: ... = panel_attr(
        "legendPosition", validators=[one_of(LEGEND_POSITIONS)]
    )
    legend_template: ... = panel_attr("legendTemplate", str)
    # panel_attr("startingXAxis")
    # panel_attr("useLocalSmoothing")
    # panel_attr("useGlobalSmoothingWeight")
    # panel_attr("legendFields")
    # panel_attr("aggregate")
    # panel_attr("aggregateMetrics")
    # panel_attr("metricRegex")
    # panel_attr("useMetricRegex")
    # panel_attr("yAxisAutoRange")
    # panel_attr("groupRunsLimit")
    # panel_attr("xExpression")
    # panel_attr("colorEachMetricDifferently")
    # panel_attr("showLegend")

    line_titles: ... = panel_attr(
        "overrideSeriesTitles",
        dict,
        fget=line_override_get,
        fset=line_override_set,
        validators=[
            type_validate(LineKey, how="keys"),
            type_validate(str, how="values"),
        ],
    )
    line_marks: ... = panel_attr(
        "overrideMarks",
        dict,
        fget=line_override_get,
        fset=line_override_set,
        validators=[type_validate(LineKey, how="keys"), one_of(MARKS, how="values")],
    )
    line_colors: ... = panel_attr(
        "overrideColors",
        dict,
        fget=line_color_override_get,
        fset=line_color_override_set,
        validators=[
            type_validate(LineKey, how="keys"),
            type_validate(RGBA, how="values"),
        ],
    )
    line_widths: ... = panel_attr(
        "overrideLineWidths",
        dict,
        fget=line_override_get,
        fset=line_override_set,
        validators=[
            type_validate(LineKey, how="keys"),
            type_validate((float, int), how="values"),
            between(0.5, 3.0, how="values"),
        ],
    )

    @property
    def view_type(self):
        return "Run History Line Plot"

    def __post_init__(self):
        super().__post_init__()


@dataclass
class ScatterPlot(Panel):
    title: ... = panel_attr("chartTitle", str)
    x: ... = panel_attr("xAxis", str)
    y: ... = panel_attr("yAxis", str)
    z: ... = panel_attr("zAxis", str)
    range_x: ... = panel_attr(
        ["xAxisMin", "xAxisMax"],
        (list, tuple),
        validators=[length(2), elem_types((int, float))],
    )
    range_y: ... = panel_attr(
        ["yAxisMin", "yAxisMax"],
        (list, tuple),
        validators=[length(2), elem_types((int, float))],
    )
    range_z: ... = panel_attr(
        ["zAxisMin", "zAxisMax"],
        (list, tuple),
        validators=[length(2), elem_types((int, float))],
    )
    log_x: ... = panel_attr("xAxisLogScale", bool)
    log_y: ... = panel_attr("yAxisLogScale", bool)
    log_z: ... = panel_attr("zAxisLogScale", bool)
    running_ymin: ... = panel_attr("showMaxYAxisLine", bool)
    running_ymax: ... = panel_attr("showMinYAxisLine", bool)
    running_ymean: ... = panel_attr("showAvgYAxisLine", bool)
    legend_template: ... = panel_attr("legendTemplate", str)

    # gradient: ... = panel_attr("customGradient", dict, validators=[type_validate(RGBA, how='values')])
    # color: ... = panel_attr("color")
    # range_color: ... = panel_attr(
    #     ["minColor", "maxColor"],
    #     (list, tuple),
    #     validators=[length(2), elem_types((int, float))],
    # )

    # panel_attr("legendFields")
    font_size: ... = panel_attr("fontSize", validators=[one_of(FONT_SIZES)])
    # panel_attr("yAxisLineSmoothingWeight")

    @property
    def view_type(self):
        return "Scatter Plot"


@dataclass
class BarPlot(Panel):
    title: ... = panel_attr("chartTitle", str)
    metrics: ... = panel_attr("metrics", list, validators=[elem_types(str)])
    vertical: ... = panel_attr("vertical", bool)
    range_x: ... = panel_attr(
        ["xAxisMin", "xAxisMax"],
        (list, tuple),
        validators=[length(2), elem_types((int, float))],
    )
    title_x: ... = panel_attr("xAxisTitle", str)
    title_y: ... = panel_attr("yAxisTitle", str)
    groupby: ... = panel_attr("groupBy", str)
    groupby_aggfunc: ... = panel_attr("groupAgg", validators=[one_of(AGGFUNCS)])
    groupby_rangefunc: ... = panel_attr("groupArea", validators=[one_of(RANGEFUNCS)])
    max_runs_to_show: ... = panel_attr("limit", int)
    max_bars_to_show: ... = panel_attr("barLimit", int)
    custom_expressions: ... = panel_attr("expressions", str)
    legend_template: ... = panel_attr("legendTemplate", str)
    font_size: ... = panel_attr("fontSize", validators=[one_of(FONT_SIZES)])
    # panel_attr("limit")
    # panel_attr("barLimit")
    # panel_attr("aggregate")
    # panel_attr("aggregateMetrics")
    # panel_attr("groupRunsLimit")
    # panel_attr("plotStyle")
    # panel_attr("legendFields")
    # panel_attr("colorEachMetricDifferently")

    line_titles: ... = panel_attr(
        "overrideSeriesTitles",
        dict,
        fget=line_override_get,
        fset=line_override_set,
        validators=[
            type_validate(LineKey, how="keys"),
            type_validate(str, how="values"),
        ],
    )
    line_colors: ... = panel_attr(
        "overrideColors",
        dict,
        fget=line_color_override_get,
        fset=line_color_override_set,
        validators=[
            type_validate(LineKey, how="keys"),
            type_validate(RGBA, how="values"),
        ],
    )

    @property
    def view_type(self):
        return "Bar Chart"


def scalar_metric_fget(prop, panel):
    return panel.config.get(prop.json_keys, [None])[0]


@panel_grid_callback
def scalar_metric_fset(prop, panel, value):
    panel.config[prop.json_keys] = [value]


@dataclass
class ScalarChart(Panel):
    title: ... = panel_attr("chartTitle", str)
    metric: ... = panel_attr(
        "metrics", str, fget=scalar_metric_fget, fset=scalar_metric_fset
    )
    groupby_aggfunc: ... = panel_attr("groupAgg", validators=[one_of(AGGFUNCS)])
    groupby_rangefunc: ... = panel_attr("groupArea", validators=[one_of(RANGEFUNCS)])
    custom_expressions: ... = panel_attr("expressions", str)
    legend_template: ... = panel_attr("legendTemplate", str)

    # panel_attr("aggregate")
    # panel_attr("aggregateMetrics")
    # panel_attr("groupBy")
    # panel_attr("groupRunsLimit")
    # panel_attr("legendFields")
    # panel_attr("showLegend")
    font_size: ... = panel_attr("fontSize", validators=[one_of(FONT_SIZES)])

    @property
    def view_type(self):
        return "Scalar Chart"


@dataclass
class CodeComparer(Panel):
    diff: ... = panel_attr("diff", validators=[one_of(CODE_COMPARE_DIFF)])

    @property
    def view_type(self):
        return "Code Comparer"


@dataclass
class ParallelCoordinatesPlot(Panel):
    columns: ... = panel_attr("columns", str)
    title: ... = panel_attr("chartTitle", str)

    # panel_attr("dimensions")
    # panel_attr("customGradient")
    # panel_attr("gradientColor")
    # panel_attr("legendFields")
    font_size: ... = panel_attr("fontSize", validators=[one_of(FONT_SIZES)])

    @property
    def view_type(self):
        return "Parallel Coordinates Plot"


@dataclass
class ParameterImportancePlot(Panel):
    with_respect_to: ... = panel_attr("targetKey")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.with_respect_to:
            self.with_respect_to = "_timestamp"

    @property
    def view_type(self):
        return "Parameter Importance"


@dataclass
class RunComparer(Panel):
    diff_only: ... = panel_attr("diffOnly", validators=[one_of(["split", None])])

    @property
    def view_type(self):
        return "Run Comparer"


@dataclass
class MediaBrowser(Panel):
    num_columns: ... = panel_attr("columnCount", int)
    media_keys: ... = panel_attr("media_keys", str)

    # panel_attr("chartTitle")
    # panel_attr("stepIndex")
    # panel_attr("mediaIndex")
    # panel_attr("actualSize")
    # panel_attr("fitToDimension")
    # panel_attr("pixelated")
    # panel_attr("mode")
    # panel_attr("gallerySettings")
    # panel_attr("gridSettings")
    # panel_attr("selection")
    # panel_attr("page")
    # panel_attr("tileLayout")
    # panel_attr("stepStrideLength")
    # panel_attr("snapToExistingStep")
    # panel_attr("maxGalleryItems")
    # panel_attr("maxYAxisCount")
    # panel_attr("moleculeConfig")
    # panel_attr("segmentationMaskConfig")
    # panel_attr("boundingBoxConfig")

    @property
    def view_type(self):
        return "Media Browser"


@dataclass
class MarkdownPanel(Panel):
    markdown: ... = panel_attr("value", str)

    @property
    def view_type(self):
        return "Markdown Panel"


@dataclass
class ConfusionMatrix(Panel):
    @property
    def view_type(self):
        return "Confusion Matrix"


@dataclass
class DataFrames(Panel):
    @property
    def view_type(self):
        return "Data Frame Table"


@dataclass
class MultiRunTable(Panel):
    @property
    def view_type(self):
        return "Multi Run Table"


@dataclass
class Vega(Panel):
    @property
    def view_type(self):
        return "Vega"


@dataclass
class Vega2(Panel):
    @property
    def view_type(self):
        return "Vega2"


@dataclass
class Vega3(Panel):
    @property
    def view_type(self):
        return "Vega3"


@dataclass
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
