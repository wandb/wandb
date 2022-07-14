from copy import deepcopy
import inspect
import json
import re
from typing import Any, Dict, List as LList
from typing import Optional, Union
import urllib

import wandb
from wandb.sdk.lib import ipython

from .mutations import CREATE_PROJECT, UPSERT_VIEW
from .util import (
    Attr,
    Base,
    Block,
    coalesce,
    fix_collisions,
    generate_name,
    nested_get,
    nested_set,
    Panel,
)
from .validators import (
    AGGFUNCS,
    Between,
    CODE_COMPARE_DIFF,
    FONT_SIZES,
    LEGEND_POSITIONS,
    Length,
    LINEPLOT_STYLES,
    MARKS,
    OneOf,
    RANGEFUNCS,
    SMOOTHING_TYPES,
    TypeValidator,
)


class LineKey:
    def __init__(self, key: str) -> None:
        self.key = key

    def __hash__(self) -> int:
        return hash(self.key)

    def __repr__(self) -> str:
        return f'LineKey(key="{self.key}")'

    @classmethod
    def from_run(cls, run: "wandb.apis.public.Run", metric: str) -> "LineKey":
        key = f"{run.id}:{metric}"
        return cls(key)

    @classmethod
    def from_panel_agg(cls, runset: "RunSet", panel: "Panel", metric: str) -> "LineKey":
        key = f"{runset.id}-config:group:{panel.groupby}:null:{metric}"
        return cls(key)

    @classmethod
    def from_runset_agg(cls, runset: "RunSet", metric: str) -> "LineKey":
        groupby = runset.groupby
        if runset.groupby is None:
            groupby = "null"

        key = f"{runset.id}-run:group:{groupby}:{metric}"
        return cls(key)


class RGBA(Base):
    r: int = Attr(validators=[Between(0, 255)])
    g: int = Attr(validators=[Between(0, 255)])
    b: int = Attr(validators=[Between(0, 255)])
    a: Union[int, float] = Attr(validators=[Between(0, 1)])

    def __init__(
        self, r: int, g: int, b: int, a: Union[int, float] = None, *args, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.r = r
        self.g = g
        self.b = b
        self.a = a

    @classmethod
    def from_json(cls, d: Dict[str, Any]) -> "RGBA":
        color = d.get("transparentColor").replace(" ", "")
        r, g, b, a = re.split(r"\(|\)|,", color)[1:-1]
        r, g, b, a = int(r), int(g), int(b), float(a)
        return cls(r, g, b, a)

    @property
    def spec(self) -> Dict[str, Any]:
        return {
            "color": f"rgb({self.r}, {self.g}, {self.b})",
            "transparentColor": f"rgba({self.r}, {self.g}, {self.b}, {self.a})",
        }


class UnknownPanel(Panel):
    @property
    def view_type(self) -> str:
        return "UNKNOWN PANEL"


class LinePlot(Panel):
    def __init__(
        self,
        title: Optional[str] = None,
        x: Optional[str] = None,
        y: Optional[list] = None,
        range_x: Union[list, tuple] = (None, None),
        range_y: Union[list, tuple] = (None, None),
        log_x: Optional[bool] = None,
        log_y: Optional[bool] = None,
        title_x: Optional[str] = None,
        title_y: Optional[str] = None,
        ignore_outliers: Optional[bool] = None,
        groupby: Optional[str] = None,
        groupby_aggfunc: Optional[str] = None,
        groupby_rangefunc: Optional[str] = None,
        smoothing_factor: Optional[float] = None,
        smoothing_type: Optional[str] = None,
        smoothing_show_original: Optional[bool] = None,
        max_runs_to_show: Optional[int] = None,
        custom_expressions: Optional[str] = None,
        plot_type: Optional[str] = None,
        font_size: Optional[str] = None,
        legend_position: Optional[str] = None,
        legend_template: Optional[str] = None,
        aggregate: Optional[bool] = None,
        xaxis_expression: Optional[str] = None,
        line_titles: Optional[dict] = None,
        line_marks: Optional[dict] = None,
        line_colors: Optional[dict] = None,
        line_widths: Optional[dict] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.title = title
        self.x = x
        self.y = y
        self.range_x = range_x
        self.range_y = range_y
        self.log_x = log_x
        self.log_y = log_y
        self.title_x = title_x
        self.title_y = title_y
        self.ignore_outliers = ignore_outliers
        self.groupby = groupby
        self.groupby_aggfunc = groupby_aggfunc
        self.groupby_rangefunc = groupby_rangefunc
        self.smoothing_factor = smoothing_factor
        self.smoothing_type = smoothing_type
        self.smoothing_show_original = smoothing_show_original
        self.max_runs_to_show = max_runs_to_show
        self.custom_expressions = custom_expressions
        self.plot_type = plot_type
        self.font_size = font_size
        self.legend_position = legend_position
        self.legend_template = legend_template
        self.aggregate = aggregate
        self.xaxis_expression = xaxis_expression
        self.line_titles = line_titles
        self.line_marks = line_marks
        self.line_colors = line_colors
        self.line_widths = line_widths

    title: Optional[str] = Attr(
        json_path="spec.config.chartTitle",
    )
    x: Optional[str] = Attr(json_path="spec.config.xAxis")
    y: Optional[list] = Attr(json_path="spec.config.metrics")
    range_x: Union[list, tuple] = Attr(
        json_path=["spec.config.xAxisMin", "spec.config.xAxisMax"],
        validators=[
            Length(2),
            TypeValidator(Optional[Union[int, float]], how="keys"),
        ],
    )
    range_y: Union[list, tuple] = Attr(
        json_path=["spec.config.yAxisMin", "spec.config.yAxisMax"],
        validators=[
            Length(2),
            TypeValidator(Optional[Union[int, float]], how="keys"),
        ],
    )
    log_x: Optional[bool] = Attr(json_path="spec.config.xLogScale")
    log_y: Optional[bool] = Attr(json_path="spec.config.xLogScale")
    title_x: Optional[str] = Attr(json_path="spec.config.xAxisTitle")
    title_y: Optional[str] = Attr(json_path="spec.config.yAxisTitle")
    ignore_outliers: Optional[bool] = Attr(json_path="spec.config.ignoreOutliers")
    groupby: Optional[str] = Attr(json_path="spec.config.groupBy")
    groupby_aggfunc: Optional[str] = Attr(
        json_path="spec.config.groupAgg",
        validators=[OneOf(AGGFUNCS)],
    )
    groupby_rangefunc: Optional[str] = Attr(
        json_path="spec.config.groupArea",
        validators=[OneOf(RANGEFUNCS)],
    )
    smoothing_factor: Optional[float] = Attr(json_path="spec.config.smoothingWeight")
    smoothing_type: Optional[str] = Attr(
        json_path="spec.config.smoothingType",
        validators=[OneOf(SMOOTHING_TYPES)],
    )
    smoothing_show_original: Optional[bool] = Attr(
        json_path="spec.config.showOriginalAfterSmoothing"
    )
    max_runs_to_show: Optional[int] = Attr(json_path="spec.config.smoothingType")
    custom_expressions: Optional[str] = Attr(json_path="spec.config.expressions")
    plot_type: Optional[str] = Attr(
        json_path="spec.config.plotType",
        validators=[OneOf(LINEPLOT_STYLES)],
    )
    font_size: Optional[str] = Attr(
        json_path="spec.config.fontSize",
        validators=[OneOf(FONT_SIZES)],
    )
    legend_position: Optional[str] = Attr(
        json_path="spec.config.legendPosition",
        validators=[OneOf(LEGEND_POSITIONS)],
    )
    legend_template: Optional[str] = Attr(json_path="spec.config.legendTemplate")
    # Attr( json_path="spec.config.startingXAxis")
    # Attr( json_path="spec.config.useLocalSmoothing")
    # Attr( json_path="spec.config.useGlobalSmoothingWeight")
    # Attr( json_path="spec.config.legendFields")
    aggregate: Optional[bool] = Attr(json_path="spec.config.aggregate")
    # Attr( json_path="spec.config.aggregateMetrics")
    # Attr( json_path="spec.config.metricRegex")
    # Attr( json_path="spec.config.useMetricRegex")
    # Attr( json_path="spec.config.yAxisAutoRange")
    # Attr( json_path="spec.config.groupRunsLimit")
    xaxis_expression: Optional[str] = Attr(json_path="spec.config.xExpression")
    # Attr( json_path="spec.config.colorEachMetricDifferently")
    # Attr( json_path="spec.config.showLegend")

    line_titles: Optional[dict] = Attr(
        json_path="spec.config.overrideSeriesTitles",
        validators=[
            TypeValidator(LineKey, how="keys"),
            TypeValidator(str, how="values"),
        ],
    )
    line_marks: Optional[dict] = Attr(
        json_path="spec.config.overrideMarks",
        validators=[
            TypeValidator(LineKey, how="keys"),
            OneOf(MARKS, how="values"),
        ],
    )
    line_colors: Optional[dict] = Attr(
        json_path="spec.config.overrideColors",
        validators=[
            TypeValidator(LineKey, how="keys"),
            TypeValidator(RGBA, how="values"),
        ],
    )
    line_widths: Optional[dict] = Attr(
        json_path="spec.config.overrideLineWidths",
        validators=[
            TypeValidator(LineKey, how="keys"),
            TypeValidator(Union[int, float], how="values"),
            Between(0.5, 3.0, how="values"),
        ],
    )

    @x.getter
    def x(self):
        json_path = self._get_path("x")
        value = nested_get(self, json_path)
        return self.panel_metrics_helper.back_to_front(value)

    @x.setter
    def x(self, value):
        json_path = self._get_path("x")
        value = self.panel_metrics_helper.front_to_back(value)
        nested_set(self, json_path, value)

    @y.getter
    def y(self):
        json_path = self._get_path("y")
        value = nested_get(self, json_path)
        if value is None:
            return value
        return [self.panel_metrics_helper.back_to_front(v) for v in value]

    @y.setter
    def y(self, value):
        json_path = self._get_path("y")
        if value is not None:
            value = [self.panel_metrics_helper.front_to_back(v) for v in value]
        nested_set(self, json_path, value)

    @property
    def view_type(self):
        return "Run History Line Plot"


class ScatterPlot(Panel):
    def __init__(
        self,
        title=None,
        x=None,
        y=None,
        z=None,
        range_x=(None, None),
        range_y=(None, None),
        range_z=(None, None),
        log_x=None,
        log_y=None,
        log_z=None,
        running_ymin=None,
        running_ymax=None,
        running_ymean=None,
        legend_template=None,
        gradient=None,
        font_size=None,
        regression=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.title = title
        self.x = x
        self.y = y
        self.z = z
        self.range_x = range_x
        self.range_y = range_y
        self.range_z = range_z
        self.log_x = log_x
        self.log_y = log_y
        self.log_z = log_z
        self.running_ymin = running_ymin
        self.running_ymax = running_ymax
        self.running_ymean = running_ymean
        self.legend_template = legend_template
        self.gradient = gradient
        self.font_size = font_size
        self.regression = regression

    title: Optional[str] = Attr(json_path="spec.config.chartTitle")
    x: Optional[str] = Attr(json_path="spec.config.xAxis")
    y: Optional[str] = Attr(json_path="spec.config.yAxis")
    z: Optional[str] = Attr(json_path="spec.config.zAxis")
    range_x: Union[list, tuple] = Attr(
        json_path=["spec.config.xAxisMin", "spec.config.xAxisMax"],
        validators=[
            Length(2),
            TypeValidator(Optional[Union[int, float]], how="keys"),
        ],
    )
    range_y: Union[list, tuple] = Attr(
        json_path=["spec.config.yAxisMin", "spec.config.yAxisMax"],
        validators=[
            Length(2),
            TypeValidator(Optional[Union[int, float]], how="keys"),
        ],
    )
    range_z: Union[list, tuple] = Attr(
        json_path=["spec.config.zAxisMin", "spec.config.zAxisMax"],
        validators=[
            Length(2),
            TypeValidator(Optional[Union[int, float]], how="keys"),
        ],
    )
    log_x: Optional[bool] = Attr(json_path="spec.config.xAxisLogScale")
    log_y: Optional[bool] = Attr(json_path="spec.config.yAxisLogScale")
    log_z: Optional[bool] = Attr(json_path="spec.config.zAxisLogScale")
    running_ymin: Optional[bool] = Attr(json_path="spec.config.showMaxYAxisLine")
    running_ymax: Optional[bool] = Attr(json_path="spec.config.showMinYAxisLine")
    running_ymean: Optional[bool] = Attr(json_path="spec.config.showAvgYAxisLine")
    legend_template: Optional[str] = Attr(json_path="spec.config.legendTemplate")
    gradient: Optional[dict] = Attr(
        json_path="spec.config.customGradient",
        validators=[TypeValidator(RGBA, how="values")],
    )
    # color: ... = Attr(json_path="spec.config.color")
    # range_color: ... = Attr(
    #     ["spec.config.minColor", "spec.config.maxColor"],
    #     (list, tuple),
    #     validators=[Length(2), TypeValidator((int, float), how='keys')],
    # )

    # Attr(json_path="spec.config.legendFields")
    font_size: Optional[str] = Attr(
        json_path="spec.config.fontSize",
        validators=[OneOf(FONT_SIZES)],
    )
    # Attr(json_path="spec.config.yAxisLineSmoothingWeight")
    regression: Optional[bool] = Attr(json_path="spec.config.showLinearRegression")

    @x.getter
    def x(self):
        json_path = self._get_path("x")
        value = nested_get(self, json_path)
        return self.panel_metrics_helper.special_back_to_front(value)

    @x.setter
    def x(self, value):
        json_path = self._get_path("x")
        value = self.panel_metrics_helper.special_front_to_back(value)
        nested_set(self, json_path, value)

    @y.getter
    def y(self):
        json_path = self._get_path("y")
        value = nested_get(self, json_path)
        return self.panel_metrics_helper.special_back_to_front(value)

    @y.setter
    def y(self, value):
        json_path = self._get_path("y")
        value = self.panel_metrics_helper.special_front_to_back(value)
        nested_set(self, json_path, value)

    @z.getter
    def z(self):
        json_path = self._get_path("z")
        value = nested_get(self, json_path)
        return self.panel_metrics_helper.special_back_to_front(value)

    @z.setter
    def z(self, value):
        json_path = self._get_path("z")
        value = self.panel_metrics_helper.special_front_to_back(value)
        nested_set(self, json_path, value)

    @property
    def view_type(self) -> str:
        return "Scatter Plot"


class BarPlot(Panel):
    def __init__(
        self,
        title=None,
        metrics=None,
        vertical=None,
        range_x=(None, None),
        title_x=None,
        title_y=None,
        groupby=None,
        groupby_aggfunc=None,
        groupby_rangefunc=None,
        max_runs_to_show=None,
        max_bars_to_show=None,
        custom_expressions=None,
        legend_template=None,
        font_size=None,
        line_titles=None,
        line_colors=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.title = title
        self.metrics = metrics
        self.vertical = vertical
        self.range_x = range_x
        self.title_x = title_x
        self.title_y = title_y
        self.groupby = groupby
        self.groupby_aggfunc = groupby_aggfunc
        self.groupby_rangefunc = groupby_rangefunc
        self.max_runs_to_show = max_runs_to_show
        self.max_bars_to_show = max_bars_to_show
        self.custom_expressions = custom_expressions
        self.legend_template = legend_template
        self.font_size = font_size
        self.line_titles = line_titles
        self.line_colors = line_colors

    title: Optional[str] = Attr(json_path="spec.config.chartTitle")
    metrics: Optional[list] = Attr(
        json_path="spec.config.metrics",
        validators=[TypeValidator(str, how="keys")],
    )
    vertical: Optional[bool] = Attr(json_path="spec.config.vertical")
    range_x: Union[list, tuple] = Attr(
        json_path=["spec.config.xAxisMin", "spec.config.xAxisMax"],
        validators=[
            Length(2),
            TypeValidator(Optional[Union[int, float]], how="keys"),
        ],
    )
    title_x: Optional[str] = Attr(json_path="spec.config.xAxisTitle")
    title_y: Optional[str] = Attr(json_path="spec.config.yAxisTitle")
    groupby: Optional[str] = Attr(json_path="spec.config.groupBy")
    groupby_aggfunc: Optional[str] = Attr(
        json_path="spec.config.groupAgg",
        validators=[OneOf(AGGFUNCS)],
    )
    groupby_rangefunc: Optional[str] = Attr(
        json_path="spec.config.groupArea",
        validators=[OneOf(RANGEFUNCS)],
    )
    max_runs_to_show: Optional[int] = Attr(json_path="spec.config.limit")
    max_bars_to_show: Optional[int] = Attr(json_path="spec.config.barLimit")
    custom_expressions: Optional[str] = Attr(json_path="spec.config.expressions")
    legend_template: Optional[str] = Attr(json_path="spec.config.legendTemplate")
    font_size: Optional[str] = Attr(
        json_path="spec.config.fontSize",
        validators=[OneOf(FONT_SIZES)],
    )
    # Attr(json_path="spec.config.limit")
    # Attr(json_path="spec.config.barLimit")
    # Attr(json_path="spec.config.aggregate")
    # Attr(json_path="spec.config.aggregateMetrics")
    # Attr(json_path="spec.config.groupRunsLimit")
    # Attr(json_path="spec.config.plotStyle")
    # Attr(json_path="spec.config.legendFields")
    # Attr(json_path="spec.config.colorEachMetricDifferently")

    line_titles: Optional[dict] = Attr(
        json_path="spec.config.overrideSeriesTitles",
        validators=[
            TypeValidator(LineKey, how="keys"),
            TypeValidator(str, how="values"),
        ],
    )
    line_colors: Optional[dict] = Attr(
        json_path="spec.config.overrideColors",
        validators=[
            TypeValidator(LineKey, how="keys"),
            TypeValidator(RGBA, how="values"),
        ],
    )

    @metrics.getter
    def metrics(self):
        json_path = self._get_path("metrics")
        value = nested_get(self, json_path)
        if value is None:
            return value
        return [self.panel_metrics_helper.back_to_front(v) for v in value]

    @metrics.setter
    def metrics(self, value):
        json_path = self._get_path("metrics")
        if value is not None:
            value = [self.panel_metrics_helper.front_to_back(v) for v in value]
        nested_set(self, json_path, value)

    @property
    def view_type(self) -> str:
        return "Bar Chart"


class ScalarChart(Panel):
    def __init__(
        self,
        title=None,
        metric=None,
        groupby_aggfunc=None,
        groupby_rangefunc=None,
        custom_expressions=None,
        legend_template=None,
        font_size=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.title = title
        self.metric = coalesce(metric, "")
        self.groupby_aggfunc = groupby_aggfunc
        self.groupby_rangefunc = groupby_rangefunc
        self.custom_expressions = custom_expressions
        self.legend_template = legend_template
        self.font_size = font_size

    title: Optional[str] = Attr(json_path="spec.config.chartTitle")
    metric: str = Attr(json_path="spec.config.metrics")
    groupby_aggfunc: Optional[str] = Attr(
        json_path="spec.config.groupAgg",
        validators=[OneOf(AGGFUNCS)],
    )
    groupby_rangefunc: Optional[str] = Attr(
        json_path="spec.config.groupArea",
        validators=[OneOf(RANGEFUNCS)],
    )
    custom_expressions: Optional[str] = Attr(json_path="spec.config.expressions")
    legend_template: Optional[str] = Attr(json_path="spec.config.legendTemplate")

    # Attr(json_path="spec.config.aggregate")
    # Attr(json_path="spec.config.aggregateMetrics")
    # Attr(json_path="spec.config.groupBy")
    # Attr(json_path="spec.config.groupRunsLimit")
    # Attr(json_path="spec.config.legendFields")
    # Attr(json_path="spec.config.showLegend")
    font_size: Optional[str] = Attr(
        json_path="spec.config.fontSize",
        validators=[OneOf(FONT_SIZES)],
    )

    @metric.getter
    def metric(self):
        json_path = self._get_path("metric")
        value = nested_get(self, json_path)[0]
        return self.panel_metrics_helper.back_to_front(value)

    @metric.setter
    def metric(self, new_metrics):
        json_path = self._get_path("metric")
        new_metrics = self.panel_metrics_helper.front_to_back(new_metrics)
        nested_set(self, json_path, [new_metrics])

    @property
    def view_type(self) -> str:
        return "Scalar Chart"


class CodeComparer(Panel):
    def __init__(self, diff=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.diff = diff

    diff: Optional[str] = Attr(
        json_path="spec.config.diff",
        validators=[OneOf(CODE_COMPARE_DIFF)],
    )

    @property
    def view_type(self) -> str:
        return "Code Comparer"


class PCColumn(Base):
    def __init__(
        self, metric, name=None, ascending=None, log_scale=None, *args, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.metric = metric
        self.name = name
        self.ascending = ascending
        self.log_scale = log_scale

    metric: str = Attr(json_path="spec.accessor")
    name: Optional[str] = Attr(json_path="spec.displayName")
    ascending: Optional[bool] = Attr(json_path="spec.inverted")
    log_scale: Optional[bool] = Attr(json_path="spec.log")

    @classmethod
    def from_json(cls, spec):
        obj = cls(metric=spec["accessor"])
        obj._spec = spec
        return obj


class ParallelCoordinatesPlot(Panel):
    def __init__(self, columns=None, title=None, font_size=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.columns = coalesce(columns, [])
        self.title = title
        self.font_size = font_size

    columns: list = Attr(
        json_path="spec.config.columns",
        validators=[TypeValidator(PCColumn, how="keys")],
    )
    title: Optional[str] = Attr(json_path="spec.config.chartTitle")

    # Attr(json_path="spec.config.dimensions")
    # Attr(json_path="spec.config.customGradient")
    # Attr(json_path="spec.config.gradientColor")
    # Attr(json_path="spec.config.legendFields")
    font_size: Optional[str] = Attr(
        json_path="spec.config.fontSize",
        validators=[OneOf(FONT_SIZES)],
    )

    @columns.getter
    def columns(self):
        json_path = self._get_path("columns")
        specs = nested_get(self, json_path)
        return [PCColumn.from_json(cspec) for cspec in specs]

    @columns.setter
    def columns(self, new_columns):
        json_path = self._get_path("columns")
        specs = [c.spec for c in new_columns]
        nested_set(self, json_path, specs)

    @property
    def view_type(self) -> str:
        return "Parallel Coordinates Plot"


class ParameterImportancePlot(Panel):
    def __init__(self, with_respect_to=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.with_respect_to = coalesce(with_respect_to, "Created Timestamp")

    with_respect_to: str = Attr(json_path="spec.config.targetKey")

    @with_respect_to.getter
    def with_respect_to(self):
        json_path = self._get_path("with_respect_to")
        value = nested_get(self, json_path)
        return self.panel_metrics_helper.back_to_front(value)

    @with_respect_to.setter
    def with_respect_to(self, value):
        json_path = self._get_path("with_respect_to")
        value = self.panel_metrics_helper.front_to_back(value)
        nested_set(self, json_path, value)

    @property
    def view_type(self) -> str:
        return "Parameter Importance"


class RunComparer(Panel):
    def __init__(self, diff_only=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.diff_only = diff_only

    diff_only: Optional[str] = Attr(
        json_path="spec.config.diffOnly",
        validators=[OneOf(["split", None])],
    )

    @property
    def view_type(self) -> str:
        return "Run Comparer"


class MediaBrowser(Panel):
    def __init__(self, num_columns=None, media_keys=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.num_columns = num_columns
        self.media_keys = media_keys

    num_columns: Optional[int] = Attr(json_path="spec.config.columnCount")
    media_keys: Optional[str] = Attr(json_path="spec.config.media_keys")

    # Attr(json_path="spec.config.chartTitle")
    # Attr(json_path="spec.config.stepIndex")
    # Attr(json_path="spec.config.mediaIndex")
    # Attr(json_path="spec.config.actualSize")
    # Attr(json_path="spec.config.fitToDimension")
    # Attr(json_path="spec.config.pixelated")
    # Attr(json_path="spec.config.mode")
    # Attr(json_path="spec.config.gallerySettings")
    # Attr(json_path="spec.config.gridSettings")
    # Attr(json_path="spec.config.selection")
    # Attr(json_path="spec.config.page")
    # Attr(json_path="spec.config.tileLayout")
    # Attr(json_path="spec.config.stepStrideLength")
    # Attr(json_path="spec.config.snapToExistingStep")
    # Attr(json_path="spec.config.maxGalleryItems")
    # Attr(json_path="spec.config.maxYAxisCount")
    # Attr(json_path="spec.config.moleculeConfig")
    # Attr(json_path="spec.config.segmentationMaskConfig")
    # Attr(json_path="spec.config.boundingBoxConfig")

    @property
    def view_type(self) -> str:
        return "Media Browser"


class MarkdownPanel(Panel):
    def __init__(self, markdown=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.markdown = markdown

    markdown: Optional[str] = Attr(json_path="spec.config.value")

    @property
    def view_type(self) -> str:
        return "Markdown Panel"


class ConfusionMatrix(Panel):
    @property
    def view_type(self) -> str:
        return "Confusion Matrix"


class DataFrames(Panel):
    @property
    def view_type(self) -> str:
        return "Data Frame Table"


class MultiRunTable(Panel):
    @property
    def view_type(self) -> str:
        return "Multi Run Table"


class Vega(Panel):
    @property
    def view_type(self) -> str:
        return "Vega"


class Vega2(Panel):
    @property
    def view_type(self) -> str:
        return "Vega2"


class Vega3(Panel):
    @property
    def view_type(self) -> str:
        return "Vega3"


class WeavePanel(Panel):
    @property
    def view_type(self) -> str:
        return "Weave"


class RunSet(Base):
    def __init__(
        self,
        entity=None,
        project="",
        name="Run set",
        query="",
        filters=None,
        groupby=None,
        order=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._spec = self._default_runset_spec()
        self.query_generator = wandb.apis.public.QueryGenerator()
        self.pm_query_generator = wandb.apis.public.PythonMongoishQueryGenerator(self)

        # self.entity = entity if entity != "" else wandb.Api().default_entity
        self.entity = coalesce(entity, wandb.Api().default_entity, "")
        self.project = project
        self.name = name
        self.query = query
        self.filters = coalesce(filters, self._default_filters())
        self.groupby = coalesce(groupby, self._default_groupby())
        self.order = coalesce(order, self._default_order())

    entity: str = Attr(json_path="spec.project.entityName")
    project: str = Attr(json_path="spec.project.name")
    name: str = Attr(json_path="spec.name")
    query: str = Attr(json_path="spec.search.query")
    filters: dict = Attr(json_path="spec.filters")
    groupby: list = Attr(json_path="spec.grouping")
    order: list = Attr(json_path="spec.sort")

    @filters.getter
    def filters(self):
        json_path = self._get_path("filters")
        filter_specs = nested_get(self, json_path)
        return self.query_generator.filter_to_mongo(filter_specs)

    @filters.setter
    def filters(self, new_filters):
        json_path = self._get_path("filters")
        new_filter_specs = self.query_generator.mongo_to_filter(new_filters)
        nested_set(self, json_path, new_filter_specs)

    def set_filters_with_python_expr(self, expr):
        self.filters = self.pm_query_generator.python_to_mongo(expr)
        return self

    @groupby.getter
    def groupby(self):
        json_path = self._get_path("groupby")
        groupby_specs = nested_get(self, json_path)
        cols = [self.query_generator.key_to_server_path(k) for k in groupby_specs]
        return [self.pm_query_generator.back_to_front(c) for c in cols]

    @groupby.setter
    def groupby(self, new_groupby):
        json_path = self._get_path("groupby")
        cols = [self.pm_query_generator.front_to_back(g) for g in new_groupby]
        new_groupby_specs = [self.query_generator.server_path_to_key(c) for c in cols]
        nested_set(self, json_path, new_groupby_specs)

    @order.getter
    def order(self):
        json_path = self._get_path("order")
        order_specs = nested_get(self, json_path)
        cols = self.query_generator.keys_to_order(order_specs)
        return [c[0] + self.pm_query_generator.back_to_front(c[1:]) for c in cols]

    @order.setter
    def order(self, new_orders):
        json_path = self._get_path("order")
        cols = [o[0] + self.pm_query_generator.front_to_back(o[1:]) for o in new_orders]
        new_order_specs = self.query_generator.order_to_keys(cols)
        nested_set(self, json_path, new_order_specs)

    @property
    def _runs_config(self) -> dict:
        # breakpoint()
        return {k: v for run in self.runs for k, v in run.config.items()}

    @property
    def runs(self) -> wandb.apis.public.Runs:
        return wandb.apis.public.Runs(wandb.Api().client, self.entity, self.project)

    @staticmethod
    def _default_filters():
        return {"$or": [{"$and": []}]}

    @staticmethod
    def _default_groupby():
        return []

    @staticmethod
    def _default_order():
        return ["-CreatedTimestamp"]

    @staticmethod
    def _default_runset_spec():
        return {
            "runFeed": {
                "version": 2,
                "columnVisible": {"run:name": False},
                "columnPinned": {},
                "columnWidths": {},
                "columnOrder": [],
                "pageSize": 10,
                "onlyShowSelected": False,
            },
            "enabled": True,
            "selections": {"root": 1, "bounds": [], "tree": []},
            "expandedRowAddresses": [],
        }


class UnknownBlock(Block):
    pass


class PanelGrid(Block):
    def __init__(self, runsets=None, panels=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spec = self._default_panel_grid_spec()
        self.runsets = coalesce(runsets, self._default_runsets())
        self.panels = coalesce(panels, self._default_panels())

    runsets: list = Attr(json_path="spec.metadata.runSets")
    panels: list = Attr(json_path="spec.metadata.panelBankSectionConfig.panels")

    @runsets.getter
    def runsets(self):
        json_path = self._get_path("runsets")
        specs = nested_get(self, json_path)
        return [RunSet.from_json(spec) for spec in specs]

    @runsets.setter
    def runsets(self, new_runsets):
        json_path = self._get_path("runsets")
        new_specs = [rs.spec for rs in new_runsets]
        nested_set(self, json_path, new_specs)

    @panels.getter
    def panels(self):
        json_path = self._get_path("panels")
        specs = nested_get(self, json_path)
        panels = []
        for pspec in specs:
            cls = panel_mapping.get(pspec["viewType"], UnknownPanel)
            if cls is UnknownPanel:
                wandb.termwarn(
                    inspect.cleandoc(
                        f"""
                        UNKNOWN PANEL DETECTED
                            This can happen if we have added new panels, but you are using an older version of the SDK.
                            If your report is loading normally, you can safely ignore this message (but we recommend not touching UnknownPanel)
                            If you think this is an error, please file a bug report including your SDK version ({wandb.__version__}) and this spec ({pspec})
                        """
                    )
                )
            panels.append(cls.from_json(pspec))
        return panels

    @panels.setter
    def panels(self, new_panels):
        json_path = self._get_path("panels")

        # For PC and Scatter, we need to use slightly different values, so update if possible.
        # This only happens on set, and only when assigned to a panel grid because that is
        # the earliest time that we have a runset to check what kind of metric is being assigned.
        new_panels = self._get_specific_keys_for_certain_plots(new_panels, setting=True)

        new_specs = [p.spec for p in fix_collisions(new_panels)]
        nested_set(self, json_path, new_specs)

    @staticmethod
    def _default_panel_grid_spec():
        return {
            "type": "panel-grid",
            "children": [{"text": ""}],
            "metadata": {
                "openViz": True,
                "panels": {
                    "views": {"0": {"name": "Panels", "defaults": [], "config": []}},
                    "tabs": ["0"],
                },
                "panelBankConfig": {
                    "state": 0,
                    "settings": {
                        "autoOrganizePrefix": 2,
                        "showEmptySections": False,
                        "sortAlphabetically": False,
                    },
                    "sections": [
                        {
                            "name": "Hidden Panels",
                            "isOpen": False,
                            "panels": [],
                            "type": "flow",
                            "flowConfig": {
                                "snapToColumns": True,
                                "columnsPerPage": 3,
                                "rowsPerPage": 2,
                                "gutterWidth": 16,
                                "boxWidth": 460,
                                "boxHeight": 300,
                            },
                            "sorted": 0,
                            "localPanelSettings": {
                                "xAxis": "_step",
                                "smoothingWeight": 0,
                                "smoothingType": "exponential",
                                "ignoreOutliers": False,
                                "xAxisActive": False,
                                "smoothingActive": False,
                            },
                        }
                    ],
                },
                "panelBankSectionConfig": {
                    "name": "Report Panels",
                    "isOpen": False,
                    "panels": [],
                    "type": "grid",
                    "flowConfig": {
                        "snapToColumns": True,
                        "columnsPerPage": 3,
                        "rowsPerPage": 2,
                        "gutterWidth": 16,
                        "boxWidth": 460,
                        "boxHeight": 300,
                    },
                    "sorted": 0,
                    "localPanelSettings": {
                        "xAxis": "_step",
                        "smoothingWeight": 0,
                        "smoothingType": "exponential",
                        "ignoreOutliers": False,
                        "xAxisActive": False,
                        "smoothingActive": False,
                    },
                },
                "customRunColors": {},
                "runSets": [],
                "openRunSet": 0,
                "name": "unused-name",
            },
        }

    @staticmethod
    def _default_runsets():
        return [RunSet()]

    @staticmethod
    def _default_panels():
        return []

    def _get_specific_keys_for_certain_plots(self, panels, setting=False):
        """
        Helper function to map names for certain plots
        """
        gen = self.runsets[0].pm_query_generator
        for p in panels:
            if isinstance(p, ParallelCoordinatesPlot):
                wandb.termlog(
                    "INFO: PCColumn metrics will be have special naming applied -- no change from you is required."
                )
                transform = gen.pc_front_to_back if setting else gen.pc_back_to_front
                if p.columns:
                    for col in p.columns:
                        col.metric = transform(col.metric)
        return panels


class Report(Base):
    def __init__(
        self,
        project,
        entity=None,
        title="Untitled Report",
        description="",
        width="readable",
        blocks=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._viewspec = self._default_viewspec()
        self._orig_viewspec = deepcopy(self._viewspec)

        self.project = project
        self.entity = coalesce(entity, wandb.Api().default_entity, "")
        self.title = title
        self.description = description
        self.width = width
        self.blocks = coalesce(blocks, [])

    project: str = Attr(json_path="viewspec.project.name")
    entity: str = Attr(json_path="viewspec.project.entityName")
    title: str = Attr(json_path="viewspec.displayName")
    description: str = Attr(json_path="viewspec.description")
    width: str = Attr(
        json_path="viewspec.spec.width",
        validators=[OneOf(["readable", "fixed", "fluid"])],
    )
    blocks: list = Attr(
        json_path="viewspec.spec.blocks",
        validators=[TypeValidator(Block, how="keys")],
    )

    @blocks.getter
    def blocks(self):
        json_path = self._get_path("blocks")
        block_specs = nested_get(self, json_path)
        blocks = []
        for bspec in block_specs:
            cls = block_mapping.get(bspec["type"], UnknownBlock)
            if cls is UnknownBlock:
                wandb.termwarn(
                    inspect.cleandoc(
                        f"""
                        UNKNOWN BLOCK DETECTED
                            This can happen if we have added new blocks, but you are using an older version of the SDK.
                            If your report is loading normally, you can safely ignore this message (but we recommend not touching UnknownPanel)
                            If you think this is an error, please file a bug report including your SDK version ({wandb.__version__}) and this spec ({bspec})
                        """
                    )
                )
            blocks.append(cls.from_json(bspec))
        return blocks[1:-1]  # accounts for hidden p blocks

    @blocks.setter
    def blocks(self, new_blocks):
        json_path = self._get_path("blocks")
        new_block_specs = (
            [P("").spec] + [b.spec for b in new_blocks] + [P("").spec]
        )  # hidden p blocks
        nested_set(self, json_path, new_block_specs)

    @staticmethod
    def _default_viewspec():
        return {
            "id": None,
            "name": None,
            "spec": {
                "version": 5,
                "panelSettings": {},
                "blocks": [],
                "width": "readable",
                "authors": [],
                "discussionThreads": [],
                "ref": {},
            },
        }

    @classmethod
    def from_json(cls, viewspec):
        obj = cls(project=viewspec["project"]["name"])
        obj._viewspec = viewspec
        obj._orig_viewspec = deepcopy(obj._viewspec)
        return obj

    @property
    def viewspec(self):
        return self._viewspec

    @property
    def modified(self) -> bool:
        return self._viewspec != self._orig_viewspec

    @property
    def spec(self) -> dict:
        return self._viewspec["spec"]

    @property
    def client(self) -> wandb.apis.public.RetryingClient:
        return wandb.Api().client

    @property
    def id(self) -> str:
        return self._viewspec["id"]

    @property
    def name(self) -> str:
        return self._viewspec["name"]

    @property
    def panel_grids(self) -> "LList[PanelGrid]":
        return [b for b in self.blocks if isinstance(b, PanelGrid)]

    @property
    def runsets(self) -> "LList[RunSet]":
        return [pg.runset for pg in self.panel_grids]

    @property
    def url(self) -> str:
        title = urllib.parse.quote(self.title.replace(" ", "-"))
        id = self.id.replace("=", "")
        return (
            f"{self.client.app_url}/{self.entity}/{self.project}/reports/{title}--{id}"
        )

    def save(self, draft: bool = False, clone: bool = False) -> "Report":
        if not self.modified:
            wandb.termwarn("Report has not been modified")

        # create project if not exists
        r = self.client.execute(
            CREATE_PROJECT, {"entityName": self.entity, "name": self.project}
        )

        r = self.client.execute(
            UPSERT_VIEW,
            variable_values={
                "id": None if clone or not self.id else self.id,
                "name": generate_name() if clone or not self.name else self.name,
                "entityName": self.entity,
                "projectName": self.project,
                "description": self.description,
                "displayName": self.title,
                "type": "runs/draft" if draft else "runs",
                "spec": json.dumps(self.spec),
            },
        )

        viewspec = r["upsertView"]["view"]
        viewspec["spec"] = json.loads(viewspec["spec"])
        if clone:
            return Report.from_json(viewspec)
        else:
            self._viewspec = viewspec
            return self

    def to_html(self, height: int = 1024, hidden: bool = False) -> str:
        """Generate HTML containing an iframe displaying this report"""
        try:
            url = self.url + "?jupyter=true"
            style = f"border:none;width:100%;height:{height}px;"
            prefix = ""
            if hidden:
                style += "display:none;"
                prefix = ipython.toggle_button("report")
            return prefix + f'<iframe src="{url}" style="{style}"></iframe>'
        except AttributeError:
            wandb.termlog("HTML repr will be available after you save the report!")

    def _repr_html_(self) -> str:
        return self.to_html()


class List(Base):
    @classmethod
    def from_json(cls, spec: dict) -> "Union[CheckedList, OrderedList, UnorderedList]":
        items = [
            item["children"][0]["children"][0]["text"] for item in spec["children"]
        ]
        checked = [item.get("checked") for item in spec["children"]]
        ordered = spec.get("ordered")

        # NAND: Either checked or ordered or neither (unordered), never both
        if all(x is None for x in checked):
            checked = None
        if checked is not None and ordered is not None:
            raise ValueError(
                "Lists can be checked, ordered or neither (unordered), but not both!"
            )

        if checked:
            return CheckedList(items, checked)
        elif ordered:
            return OrderedList(items)
        else:
            return UnorderedList(items)


class CheckedList(Block, List):
    def __init__(self, items, checked, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = items
        self.checked = checked

    items: list = Attr()
    checked: list = Attr()

    @property
    def spec(self) -> dict:
        return {
            "type": "list",
            "children": [
                {
                    "type": "list-item",
                    "children": [{"type": "paragraph", "children": [{"text": item}]}],
                    "checked": check,
                }
                for item, check in zip(self.items, self.checked)
            ],
        }


class OrderedList(Block, List):
    def __init__(self, items, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = items

    items: list = Attr()

    @property
    def spec(self) -> dict:
        return {
            "type": "list",
            "ordered": True,
            "children": [
                {
                    "type": "list-item",
                    "children": [{"type": "paragraph", "children": [{"text": item}]}],
                    "ordered": True,
                }
                for item in self.items
            ],
        }


class UnorderedList(Block, List):
    def __init__(self, items, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = items

    items: list = Attr()

    @property
    def spec(self) -> dict:
        return {
            "type": "list",
            "children": [
                {
                    "type": "list-item",
                    "children": [{"type": "paragraph", "children": [{"text": item}]}],
                }
                for item in self.items
            ],
        }


class Heading(Base):
    @classmethod
    def from_json(cls, spec: dict) -> "Union[H1,H2,H3]":
        level = spec["level"]
        text = spec["children"][0]["text"]

        level_mapping = {1: H1, 2: H2, 3: H3}

        if level not in level_mapping:
            raise ValueError(f"`level` must be one of {list(level_mapping.keys())}")

        return level_mapping[level](text)


class H1(Block, Heading):
    def __init__(self, text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    text: str = Attr()

    @property
    def spec(self) -> dict:
        return {
            "type": "heading",
            "children": [{"text": self.text}],
            "level": 1,
        }


class H2(Block, Heading):
    def __init__(self, text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    text: str = Attr()

    @property
    def spec(self) -> dict:
        return {
            "type": "heading",
            "children": [{"text": self.text}],
            "level": 2,
        }


class H3(Block, Heading):
    def __init__(self, text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    text: str = Attr()

    @property
    def spec(self) -> dict:
        return {
            "type": "heading",
            "children": [{"text": self.text}],
            "level": 3,
        }


class BlockQuote(Block):
    def __init__(self, text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    text: str = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "BlockQuote":
        text = spec["children"][0]["text"]
        return cls(text)

    @property
    def spec(self) -> dict:
        return {"type": "block-quote", "children": [{"text": self.text}]}


class CalloutBlock(Block):
    def __init__(self, text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    text: Union[str, list] = Attr()

    def __post_init__(self) -> None:
        if isinstance(self.text, str):
            self.text = self.text.split("\n")

    @classmethod
    def from_json(cls, spec: dict) -> "CalloutBlock":
        text = [child["children"][0]["text"] for child in spec["children"]]
        return cls(text)

    @property
    def spec(self) -> dict:
        return {
            "type": "callout-block",
            "children": [
                {"type": "callout-line", "children": [{"text": text}]}
                for text in self.text
            ],
        }


class CodeBlock(Block):
    def __init__(self, code, language=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.code = code
        self.language = coalesce(language, "python")

    code: Union[str, list] = Attr()
    language: str = Attr()

    def __post_init__(self) -> None:
        if isinstance(self.code, str):
            self.code = self.code.split("\n")

    @classmethod
    def from_json(cls, spec: dict) -> "CodeBlock":
        code = [child["children"][0]["text"] for child in spec["children"]]
        language = spec.get("language", "python")
        return cls(code, language)

    @property
    def spec(self) -> dict:
        language = self.language.lower()
        return {
            "type": "code-block",
            "children": [
                {
                    "type": "code-line",
                    "children": [{"text": text}],
                    "language": language,
                }
                for text in self.code
            ],
            "language": language,
        }


class MarkdownBlock(Block):
    def __init__(self, text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text
        if isinstance(self.text, list):
            self.text = "\n".join(self.text)

    text: Union[str, list] = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "MarkdownBlock":
        text = spec["content"]
        return cls(text)

    @property
    def spec(self) -> dict:
        return {
            "type": "markdown-block",
            "children": [{"text": ""}],
            "content": self.text,
        }


class LaTeXBlock(Block):
    def __init__(self, text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text
        if isinstance(self.text, list):
            self.text = "\n".join(self.text)

    text: Union[str, list] = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "LaTeXBlock":
        text = spec["content"]
        return cls(text)

    @property
    def spec(self) -> dict:
        return {
            "type": "latex",
            "children": [{"text": ""}],
            "content": self.text,
            "block": True,
        }


class Gallery(Block):
    def __init__(self, ids, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = ids

    ids: list = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "Gallery":
        ids = spec["ids"]
        return cls(ids)

    @classmethod
    def from_report_urls(cls, urls: LList[str]) -> "Gallery":
        ids = [url.split("--")[-1] for url in urls]
        return cls(ids)

    @property
    def spec(self) -> dict:
        return {"type": "gallery", "children": [{"text": ""}], "ids": self.ids}


class Image(Block):
    def __init__(self, url, caption, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.url = url
        self.caption = caption

    url: str = Attr()
    caption: str = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "Image":
        url = spec["url"]
        caption = spec["children"][0]["text"] if spec.get("hasCaption") else None
        return cls(url, caption)

    @property
    def spec(self) -> dict:
        if self.caption:
            return {
                "type": "image",
                "children": [{"text": self.caption}],
                "url": self.url,
                "hasCaption": True,
            }
        else:
            return {"type": "image", "children": [{"text": ""}], "url": self.url}


class WeaveBlock(Block):
    def __init__(self, spec, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.spec = spec

    spec: dict = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "WeaveBlock":
        return cls(spec)


class HorizontalRule(Block):
    @classmethod
    def from_json(cls, spec: dict) -> "HorizontalRule":
        return cls()

    @property
    def spec(self):
        return {"type": "horizontal-rule", "children": [{"text": ""}]}


class TableOfContents(Block):
    @classmethod
    def from_json(cls, spec: dict) -> "TableOfContents":
        return cls()

    @property
    def spec(self) -> dict:
        return {"type": "table-of-contents", "children": [{"text": ""}]}


class SoundCloud(Block):
    def __init__(self, url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.url = url

    url: str = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "SoundCloud":
        quoted_url = spec["html"].split("url=")[-1].split("&show_artwork")[0]
        url = urllib.parse.unquote(quoted_url)
        return cls(url)

    @property
    def spec(self) -> dict:
        quoted_url = urllib.parse.quote(self.url)
        return {
            "type": "soundcloud",
            "html": f'<iframe width="100%" height="400" scrolling="no" frameborder="no" src="https://w.soundcloud.com/player/?visual=true&url={quoted_url}&show_artwork=true"></iframe>',
            "children": [{"text": ""}],
        }


class Twitter(Block):
    def __init__(self, embed_html, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.embed_html = embed_html
        if self.embed_html:
            pattern = r" <script[\s\S]+?/script>"
            self.embed_html = re.sub(pattern, "\n", self.embed_html)

    embed_html: str = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "Twitter":
        embed_html = spec["html"]
        return cls(embed_html)

    @property
    def spec(self) -> dict:
        return {"type": "twitter", "html": self.embed_html, "children": [{"text": ""}]}


class Spotify(Block):
    def __init__(self, spotify_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.spotify_id = spotify_id

    spotify_id: str = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "Spotify":
        return cls(spec["spotifyID"])

    @classmethod
    def from_url(cls, url: str) -> "Spotify":
        spotify_id = url.split("/")[-1].split("?")[0]
        return cls(spotify_id)

    @property
    def spec(self) -> dict:
        return {
            "type": "spotify",
            "spotifyType": "track",
            "spotifyID": self.spotify_id,
            "children": [{"text": ""}],
        }


class Video(Block):
    def __init__(self, url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.url = url

    url: str = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "Video":
        return cls(spec["url"])

    @property
    def spec(self) -> dict:
        return {
            "type": "video",
            "url": self.url,
            "children": [{"text": ""}],
        }


class InlineLaTeX(Base):
    def __init__(self, latex, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.latex = latex

    latex: str = Attr()

    @property
    def spec(self) -> dict:
        return {"type": "latex", "children": [{"text": ""}], "content": self.latex}


class InlineCode(Base):
    def __init__(self, code, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.code = code

    code: str = Attr()

    @property
    def spec(self) -> dict:
        return {"text": self.code, "inlineCode": True}


class P(Block):
    def __init__(self, text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    text: Union[str, InlineLaTeX, InlineCode, list] = Attr()

    @classmethod
    def from_json(cls, spec):
        if isinstance(spec["children"], str):
            text = spec["children"]
        else:
            text = []
            for elem in spec["children"]:
                if elem.get("type") == "latex":
                    text.append(InlineLaTeX(elem["content"]))
                elif elem.get("inlineCode"):
                    text.append(InlineCode(elem["text"]))
                else:
                    text.append(elem["text"])

        if not isinstance(text, list):
            text = [text]
        return cls(text)

    @property
    def spec(self) -> dict:
        if isinstance(self.text, list):
            content = [
                t.spec if not isinstance(t, str) else {"text": t} for t in self.text
            ]
        else:
            content = [{"text": self.text}]

        return {"type": "paragraph", "children": content}


block_mapping = {
    "block-quote": BlockQuote,
    "callout-block": CalloutBlock,
    "code-block": CodeBlock,
    "gallery": Gallery,
    "heading": Heading,
    "horizontal-rule": HorizontalRule,
    "image": Image,
    "latex": LaTeXBlock,
    "list": List,
    "markdown-block": MarkdownBlock,
    "panel-grid": PanelGrid,
    "paragraph": P,
    "table-of-contents": TableOfContents,
    "weave-panel": WeaveBlock,
    "video": Video,
    "spotify": Spotify,
    "twitter": Twitter,
    "soundcloud": SoundCloud,
}

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
