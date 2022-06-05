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

from functools import wraps
from typing import List, Union

from wandb.sdk.wandb_require_helpers import RequiresReportEditingMixin

from ._panel_helpers import LineKey, RGBA
from .util import Attr, generate_name, is_none, SubclassOnlyABC, UNDEFINED_TYPE
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
    """
    Attr that reads from and writes to panel config
    """

    def __init__(
        self,
        json_keys: Union[str, List[str]],
        attr_type=UNDEFINED_TYPE,
        fget: callable = default_fget,
        fset: callable = default_fset,
        fdel: callable = default_fdel,
        *args,
        **kwargs,
    ):
        super().__init__(attr_type, fget, fset, fdel, *args, **kwargs)
        self.json_keys = json_keys


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
            "__id__": generate_name(),
            "viewType": self.view_type,
            "config": {},
            # "ref": None,
            "layout": {"x": 0, "y": 0, "w": 8, "h": 6},
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


def line_override_get(attr, panel):
    titles = panel.config.get(attr.json_keys, {})
    return {LineKey(k): v for k, v in titles.items()}


def line_override_set(attr, panel, value):
    titles = {linekey.key: v for linekey, v in value.items()}
    panel.config[attr.json_keys] = titles


def line_color_override_get(attr, panel):
    colors = panel.config.get(attr.json_keys, {})
    return {LineKey(k): RGBA.from_json(v) for k, v in colors.items()}


def line_color_override_set(attr, panel, colors):
    colors = {linekey.key: v.spec for linekey, v in colors.items()}
    panel.config[attr.json_keys] = colors


class LinePlot(Panel):
    title = PanelAttr("chartTitle", str)
    x = PanelAttr("xAxis", str)
    y = PanelAttr("metrics", list)
    range_x = PanelAttr(
        ["xAxisMin", "xAxisMax"],
        (list, tuple),
        validators=[length(2), elem_types((int, float))],
    )
    range_y = PanelAttr(
        ["yAxisMin", "yAxisMax"],
        (list, tuple),
        validators=[length(2), elem_types((int, float))],
    )
    log_x = PanelAttr("xLogScale", bool)
    log_y = PanelAttr("yLogScale", bool)
    title_x = PanelAttr("xAxisTitle", str)
    title_y = PanelAttr("yAxisTitle", str)
    ignore_outliers = PanelAttr("ignoreOutliers", bool)
    groupby = PanelAttr("groupBy", str)
    groupby_aggfunc = PanelAttr("groupAgg", validators=[one_of(AGGFUNCS)])
    groupby_rangefunc = PanelAttr("groupArea", validators=[one_of(RANGEFUNCS)])
    smoothing_factor = PanelAttr("smoothingWeight", float)
    smoothing_type = PanelAttr("smoothingType", validators=[one_of(SMOOTHING_TYPES)])
    smoothing_show_original = PanelAttr("showOriginalAfterSmoothing", bool)
    max_runs_to_show = PanelAttr("limit", int)
    custom_expressions = PanelAttr("expressions", str)
    plot_type = PanelAttr("plotType", validators=[one_of(LINEPLOT_STYLES)])
    font_size = PanelAttr("fontSize", validators=[one_of(FONT_SIZES)])
    legend_position = PanelAttr("legendPosition", validators=[one_of(LEGEND_POSITIONS)])
    legend_template = PanelAttr("legendTemplate", str)
    # PanelAttr("startingXAxis")
    # PanelAttr("useLocalSmoothing")
    # PanelAttr("useGlobalSmoothingWeight")
    # PanelAttr("legendFields")
    # PanelAttr("aggregate")
    # PanelAttr("aggregateMetrics")
    # PanelAttr("metricRegex")
    # PanelAttr("useMetricRegex")
    # PanelAttr("yAxisAutoRange")
    # PanelAttr("groupRunsLimit")
    # PanelAttr("xExpression")
    # PanelAttr("colorEachMetricDifferently")
    # PanelAttr("showLegend")

    line_titles = PanelAttr(
        "overrideSeriesTitles",
        dict,
        fget=line_override_get,
        fset=line_override_set,
        validators=[
            type_validate(LineKey, how="keys"),
            type_validate(str, how="values"),
        ],
    )
    line_marks = PanelAttr(
        "overrideMarks",
        dict,
        fget=line_override_get,
        fset=line_override_set,
        validators=[type_validate(LineKey, how="keys"), one_of(MARKS, how="values")],
    )
    line_colors = PanelAttr(
        "overrideColors",
        dict,
        fget=line_color_override_get,
        fset=line_color_override_set,
        validators=[
            type_validate(LineKey, how="keys"),
            type_validate(RGBA, how="values"),
        ],
    )
    line_widths = PanelAttr(
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


class ScatterPlot(Panel):
    title = PanelAttr("chartTitle", str)
    x = PanelAttr("xAxis", str)
    y = PanelAttr("yAxis", str)
    z = PanelAttr("zAxis", str)
    range_x = PanelAttr(
        ["xAxisMin", "xAxisMax"],
        (list, tuple),
        validators=[length(2), elem_types((int, float))],
    )
    range_y = PanelAttr(
        ["yAxisMin", "yAxisMax"],
        (list, tuple),
        validators=[length(2), elem_types((int, float))],
    )
    range_z = PanelAttr(
        ["zAxisMin", "zAxisMax"],
        (list, tuple),
        validators=[length(2), elem_types((int, float))],
    )
    log_x = PanelAttr("xAxisLogScale", bool)
    log_y = PanelAttr("yAxisLogScale", bool)
    log_z = PanelAttr("zAxisLogScale", bool)
    running_ymin = PanelAttr("showMaxYAxisLine", bool)
    running_ymax = PanelAttr("showMinYAxisLine", bool)
    running_ymean = PanelAttr("showAvgYAxisLine", bool)
    legend_template = PanelAttr("legendTemplate", str)

    # gradient = PanelAttr("customGradient", dict, validators=[type_validate(RGBA, how='values')])
    # color = PanelAttr("color")
    # range_color = PanelAttr(
    #     ["minColor", "maxColor"],
    #     (list, tuple),
    #     validators=[length(2), elem_types((int, float))],
    # )

    # PanelAttr("legendFields")
    font_size = PanelAttr("fontSize", validators=[one_of(FONT_SIZES)])
    # PanelAttr("yAxisLineSmoothingWeight")

    @property
    def view_type(self):
        return "Scatter Plot"


class BarPlot(Panel):
    title = PanelAttr("chartTitle", str)
    metrics = PanelAttr("metrics", list, validators=[elem_types(str)])
    vertical = PanelAttr("vertical", bool)
    range_x = PanelAttr(
        ["xAxisMin", "xAxisMax"],
        (list, tuple),
        validators=[length(2), elem_types((int, float))],
    )
    title_x = PanelAttr("xAxisTitle", str)
    title_y = PanelAttr("yAxisTitle", str)
    groupby = PanelAttr("groupBy", str)
    groupby_aggfunc = PanelAttr("groupAgg", validators=[one_of(AGGFUNCS)])
    groupby_rangefunc = PanelAttr("groupArea", validators=[one_of(RANGEFUNCS)])
    max_runs_to_show = PanelAttr("limit", int)
    max_bars_to_show = PanelAttr("barLimit", int)
    custom_expressions = PanelAttr("expressions", str)
    legend_template = PanelAttr("legendTemplate", str)
    font_size = PanelAttr("fontSize", validators=[one_of(FONT_SIZES)])
    # PanelAttr("limit")
    # PanelAttr("barLimit")
    # PanelAttr("aggregate")
    # PanelAttr("aggregateMetrics")
    # PanelAttr("groupRunsLimit")
    # PanelAttr("plotStyle")
    # PanelAttr("legendFields")
    # PanelAttr("colorEachMetricDifferently")

    line_titles = PanelAttr(
        "overrideSeriesTitles",
        dict,
        fget=line_override_get,
        fset=line_override_set,
        validators=[
            type_validate(LineKey, how="keys"),
            type_validate(str, how="values"),
        ],
    )
    line_colors = PanelAttr(
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


class ScalarChart(Panel):
    title = PanelAttr("chartTitle", str)
    metric = PanelAttr("metrics", str, fget=scalar_metric_fget, fset=scalar_metric_fset)
    groupby_aggfunc = PanelAttr("groupAgg", validators=[one_of(AGGFUNCS)])
    groupby_rangefunc = PanelAttr("groupArea", validators=[one_of(RANGEFUNCS)])
    custom_expressions = PanelAttr("expressions", str)
    legend_template = PanelAttr("legendTemplate", str)

    # PanelAttr("aggregate")
    # PanelAttr("aggregateMetrics")
    # PanelAttr("groupBy")
    # PanelAttr("groupRunsLimit")
    # PanelAttr("legendFields")
    # PanelAttr("showLegend")
    font_size = PanelAttr("fontSize", validators=[one_of(FONT_SIZES)])

    @property
    def view_type(self):
        return "Scalar Chart"


class CodeComparer(Panel):
    diff = PanelAttr("diff", validators=[one_of(CODE_COMPARE_DIFF)])

    @property
    def view_type(self):
        return "Code Comparer"


class ParallelCoordinatesPlot(Panel):
    columns = PanelAttr("columns", str)
    title = PanelAttr("chartTitle", str)

    # PanelAttr("dimensions")
    # PanelAttr("customGradient")
    # PanelAttr("gradientColor")
    # PanelAttr("legendFields")
    font_size = PanelAttr("fontSize", validators=[one_of(FONT_SIZES)])

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
    diff_only = PanelAttr("diffOnly", validators=[one_of(["split", None])])

    @property
    def view_type(self):
        return "Run Comparer"


class MediaBrowser(Panel):
    num_columns = PanelAttr("columnCount", int)
    media_keys = PanelAttr("media_keys", str)

    # PanelAttr("chartTitle")
    # PanelAttr("stepIndex")
    # PanelAttr("mediaIndex")
    # PanelAttr("actualSize")
    # PanelAttr("fitToDimension")
    # PanelAttr("pixelated")
    # PanelAttr("mode")
    # PanelAttr("gallerySettings")
    # PanelAttr("gridSettings")
    # PanelAttr("selection")
    # PanelAttr("page")
    # PanelAttr("tileLayout")
    # PanelAttr("stepStrideLength")
    # PanelAttr("snapToExistingStep")
    # PanelAttr("maxGalleryItems")
    # PanelAttr("maxYAxisCount")
    # PanelAttr("moleculeConfig")
    # PanelAttr("segmentationMaskConfig")
    # PanelAttr("boundingBoxConfig")

    @property
    def view_type(self):
        return "Media Browser"


class MarkdownPanel(Panel):
    markdown = PanelAttr("value", str)

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
