from typing import Optional, Union

from .helpers import LineKey, PCColumn
from .util import Attr, Panel, coalesce, nested_get, nested_set
from .validators import (
    AGGFUNCS,
    CODE_COMPARE_DIFF,
    FONT_SIZES,
    LEGEND_POSITIONS,
    LINEPLOT_STYLES,
    RANGEFUNCS,
    SMOOTHING_TYPES,
    Length,
    OneOf,
    TypeValidator,
)


class UnknownPanel(Panel):
    @property
    def view_type(self) -> str:
        return "UNKNOWN PANEL"


class LinePlot(Panel):
    title: Optional[str] = Attr(
        json_path="spec.config.chartTitle",
    )
    x: Optional[str] = Attr(json_path="spec.config.xAxis")
    y: Optional[Union[list, str]] = Attr(json_path="spec.config.metrics")
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
    log_y: Optional[bool] = Attr(json_path="spec.config.yLogScale")
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
    max_runs_to_show: Optional[int] = Attr(json_path="spec.config.limit")
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
    group_runs_limit: Optional[int] = Attr(json_path="spec.config.groupRunsLimit")
    xaxis_expression: Optional[str] = Attr(json_path="spec.config.xExpression")
    # Attr( json_path="spec.config.colorEachMetricDifferently")
    # Attr( json_path="spec.config.showLegend")

    # line_titles: Optional[dict] = Attr(
    #     json_path="spec.config.overrideSeriesTitles",
    #     validators=[
    #         TypeValidator(LineKey, how="keys"),
    #         TypeValidator(str, how="values"),
    #     ],
    # )
    # line_marks: Optional[dict] = Attr(
    #     json_path="spec.config.overrideMarks",
    #     validators=[
    #         TypeValidator(LineKey, how="keys"),
    #         OneOf(MARKS, how="values"),
    #     ],
    # )
    # line_colors: Optional[dict] = Attr(
    #     json_path="spec.config.overrideColors",
    #     validators=[
    #         TypeValidator(LineKey, how="keys"),
    #     ],
    # )
    # line_widths: Optional[dict] = Attr(
    #     json_path="spec.config.overrideLineWidths",
    #     validators=[
    #         TypeValidator(LineKey, how="keys"),
    #         TypeValidator(Union[int, float], how="values"),
    #         Between(0.5, 3.0, how="values"),
    #     ],
    # )

    def __init__(
        self,
        title: Optional[str] = None,
        x: Optional[str] = None,
        y: Optional[Union[list, str]] = None,
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
        group_runs_limit: Optional[int] = None,
        xaxis_expression: Optional[str] = None,
        # line_titles: Optional[dict] = None,
        # line_marks: Optional[dict] = None,
        # line_colors: Optional[dict] = None,
        # line_widths: Optional[dict] = None,
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
        self.group_runs_limit = group_runs_limit
        self.xaxis_expression = xaxis_expression
        # self.line_titles = line_titles
        # self.line_marks = line_marks
        # self.line_colors = line_colors
        # self.line_widths = line_widths

    @x.getter
    def x(self):
        json_path = self._get_path("x")
        value = nested_get(self, json_path)
        return self.panel_metrics_helper.back_to_front(value)

    @x.setter
    def x(self, value):
        if value is None:
            value = "Step"

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
            if not isinstance(value, list):
                value = [value]
            value = [self.panel_metrics_helper.front_to_back(v) for v in value]
        nested_set(self, json_path, value)

    @property
    def view_type(self):
        return "Run History Line Plot"


class ScatterPlot(Panel):
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
    running_ymin: Optional[bool] = Attr(json_path="spec.config.showMinYAxisLine")
    running_ymax: Optional[bool] = Attr(json_path="spec.config.showMaxYAxisLine")
    running_ymean: Optional[bool] = Attr(json_path="spec.config.showAvgYAxisLine")
    legend_template: Optional[str] = Attr(json_path="spec.config.legendTemplate")
    gradient: Optional[dict] = Attr(
        json_path="spec.config.customGradient",
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
    title: Optional[str] = Attr(json_path="spec.config.chartTitle")
    metrics: Optional[Union[list, str]] = Attr(
        json_path="spec.config.metrics",
        validators=[TypeValidator(str, how="keys")],
    )
    orientation: str = Attr(
        json_path="spec.config.vertical", validators=[OneOf(["v", "h"])]
    )
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
        ],
    )

    def __init__(
        self,
        title=None,
        metrics=None,
        orientation="h",
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
        self.orientation = orientation
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
            if not isinstance(value, list):
                value = [value]
            value = [self.panel_metrics_helper.front_to_back(v) for v in value]
        nested_set(self, json_path, value)

    @orientation.getter
    def orientation(self):
        json_path = self._get_path("orientation")
        value = nested_get(self, json_path)
        return "v" if value is True else "h"

    @orientation.setter
    def orientation(self, value):
        json_path = self._get_path("orientation")
        value = True if value == "v" else False
        nested_set(self, json_path, value)

    @property
    def view_type(self) -> str:
        return "Bar Chart"


class ScalarChart(Panel):
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
    diff: Optional[str] = Attr(
        json_path="spec.config.diff",
        validators=[OneOf(CODE_COMPARE_DIFF)],
    )

    def __init__(self, diff=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.diff = diff

    @property
    def view_type(self) -> str:
        return "Code Comparer"


class ParallelCoordinatesPlot(Panel):
    columns: list = Attr(
        json_path="spec.config.columns",
        validators=[TypeValidator(Union[PCColumn, str], how="keys")],
    )
    title: Optional[str] = Attr(json_path="spec.config.chartTitle")
    gradient: Optional[list] = Attr(json_path="spec.config.customGradient")

    # Attr(json_path="spec.config.dimensions")
    # Attr(json_path="spec.config.gradientColor")
    # Attr(json_path="spec.config.legendFields")
    font_size: Optional[str] = Attr(
        json_path="spec.config.fontSize",
        validators=[OneOf(FONT_SIZES)],
    )

    def __init__(self, columns=None, title=None, font_size=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.columns = coalesce(columns, [])
        self.title = title
        self.font_size = font_size

    @columns.getter
    def columns(self):
        json_path = self._get_path("columns")
        specs = nested_get(self, json_path)
        return [PCColumn.from_json(cspec) for cspec in specs]

    @columns.setter
    def columns(self, new_columns):
        json_path = self._get_path("columns")
        cols = []
        for c in new_columns:
            if isinstance(c, PCColumn):
                cols.append(c)
            else:
                cols.append(PCColumn(c))
        specs = [c.spec for c in cols]
        nested_set(self, json_path, specs)

    @property
    def view_type(self) -> str:
        return "Parallel Coordinates Plot"


class ParameterImportancePlot(Panel):
    with_respect_to: str = Attr(json_path="spec.config.targetKey")

    def __init__(self, with_respect_to=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.with_respect_to = coalesce(with_respect_to, "Created Timestamp")

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
    num_columns: Optional[int] = Attr(json_path="spec.config.columnCount")
    media_keys: Optional[str] = Attr(json_path="spec.config.mediaKeys")
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

    def __init__(self, num_columns=None, media_keys=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.num_columns = num_columns
        self.media_keys = media_keys

    @property
    def view_type(self) -> str:
        return "Media Browser"


class MarkdownPanel(Panel):
    markdown: Optional[str] = Attr(json_path="spec.config.value")

    def __init__(self, markdown=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.markdown = markdown

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


class CustomChart(Panel):
    query: dict = Attr(json_path="spec.config.userQuery.queryFields")
    chart_name: str = Attr(json_path="spec.config.panelDefId")
    chart_fields: dict = Attr(json_path="spec.config.fieldSettings")
    chart_strings: dict = Attr(json_path="spec.config.stringSettings")

    def __init__(
        self,
        query=None,
        chart_name="",
        chart_fields=None,
        chart_strings=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.spec["config"] = {"transform": {"name": "tableWithLeafColNames"}}
        self.query = coalesce(query, {})
        self.chart_name = chart_name
        self.chart_fields = coalesce(chart_fields, {})
        self.chart_strings = coalesce(chart_strings, {})

    @classmethod
    def from_table(cls, table_name, chart_fields=None, chart_strings=None):
        return CustomChart(
            query={"summaryTable": {"tableKey": table_name}},
            chart_fields=chart_fields,
            chart_strings=chart_strings,
        )

    @property
    def view_type(self) -> str:
        return "Vega2"

    @query.getter
    def query(self):
        def fields_to_dict(fields):
            d = {}
            for field in fields:
                keys = set(field.keys())
                name = field["name"]

                if keys == {"name", "fields"}:
                    d[name] = {}
                elif keys == {"name", "value"}:
                    d[name] = field["value"]
                elif keys == {"name", "args", "fields"}:
                    d[name] = fields_to_dict(field["args"])
            return d

        fields = nested_get(self, self._get_path("query"))
        return fields_to_dict(fields)

    @query.setter
    def query(self, d):
        def dict_to_fields(d):
            fields = []
            for k, v in d.items():
                if isinstance(v, dict) and len(v) > 0:
                    field = {"name": k, "args": dict_to_fields(v), "fields": []}
                elif isinstance(v, dict) and len(v) == 0 or v is None:
                    field = {"name": k, "fields": []}
                else:
                    field = {"name": k, "value": v}
                fields.append(field)
            return fields

        d.setdefault("id", [])
        d.setdefault("name", [])

        _query = [
            {
                "args": [
                    {"name": "runSets", "value": r"${runSets}"},
                    {"name": "limit", "value": 500},
                ],
                "fields": dict_to_fields(d),
                "name": "runSets",
            }
        ]
        nested_set(self, self._get_path("query"), _query)


class Vega3(Panel):
    @property
    def view_type(self) -> str:
        return "Vega3"


class WeavePanel(Panel):
    @property
    def view_type(self) -> str:
        return "Weave"


class WeavePanelSummaryTable(Panel):
    table_name: Optional[str] = Attr(
        json_path="spec.config.panel2Config.exp.fromOp.inputs.key.val"
    )

    def __init__(self, table_name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spec["config"] = self._default_config()
        self.table_name = table_name

    @classmethod
    def from_json(cls, spec):
        table_name = spec["config"]["panel2Config"]["exp"]["fromOp"]["inputs"]["key"][
            "val"
        ]
        return cls(table_name)

    @property
    def view_type(self) -> str:
        return "Weave"

    @staticmethod
    def _default_config():
        return {
            "panel2Config": {
                "exp": {
                    "nodeType": "output",
                    "type": {
                        "type": "tagged",
                        "tag": {
                            "type": "tagged",
                            "tag": {
                                "type": "typedDict",
                                "propertyTypes": {
                                    "entityName": "string",
                                    "projectName": "string",
                                },
                            },
                            "value": {
                                "type": "typedDict",
                                "propertyTypes": {
                                    "project": "project",
                                    "filter": "string",
                                    "order": "string",
                                },
                            },
                        },
                        "value": {
                            "type": "list",
                            "objectType": {
                                "type": "tagged",
                                "tag": {
                                    "type": "typedDict",
                                    "propertyTypes": {"run": "run"},
                                },
                                "value": {
                                    "type": "union",
                                    "members": [
                                        {
                                            "type": "file",
                                            "extension": "json",
                                            "wbObjectType": {
                                                "type": "table",
                                                "columnTypes": {},
                                            },
                                        },
                                        "none",
                                    ],
                                },
                            },
                            "maxLength": 50,
                        },
                    },
                    "fromOp": {
                        "name": "pick",
                        "inputs": {
                            "obj": {
                                "nodeType": "output",
                                "type": {
                                    "type": "tagged",
                                    "tag": {
                                        "type": "tagged",
                                        "tag": {
                                            "type": "typedDict",
                                            "propertyTypes": {
                                                "entityName": "string",
                                                "projectName": "string",
                                            },
                                        },
                                        "value": {
                                            "type": "typedDict",
                                            "propertyTypes": {
                                                "project": "project",
                                                "filter": "string",
                                                "order": "string",
                                            },
                                        },
                                    },
                                    "value": {
                                        "type": "list",
                                        "objectType": {
                                            "type": "tagged",
                                            "tag": {
                                                "type": "typedDict",
                                                "propertyTypes": {"run": "run"},
                                            },
                                            "value": {
                                                "type": "union",
                                                "members": [
                                                    {
                                                        "type": "typedDict",
                                                        "propertyTypes": {
                                                            "_wandb": {
                                                                "type": "typedDict",
                                                                "propertyTypes": {
                                                                    "runtime": "number"
                                                                },
                                                            }
                                                        },
                                                    },
                                                    {
                                                        "type": "typedDict",
                                                        "propertyTypes": {
                                                            "_step": "number",
                                                            "table": {
                                                                "type": "file",
                                                                "extension": "json",
                                                                "wbObjectType": {
                                                                    "type": "table",
                                                                    "columnTypes": {},
                                                                },
                                                            },
                                                            "_wandb": {
                                                                "type": "typedDict",
                                                                "propertyTypes": {
                                                                    "runtime": "number"
                                                                },
                                                            },
                                                            "_runtime": "number",
                                                            "_timestamp": "number",
                                                        },
                                                    },
                                                ],
                                            },
                                        },
                                        "maxLength": 50,
                                    },
                                },
                                "fromOp": {
                                    "name": "run-summary",
                                    "inputs": {
                                        "run": {
                                            "nodeType": "var",
                                            "type": {
                                                "type": "tagged",
                                                "tag": {
                                                    "type": "tagged",
                                                    "tag": {
                                                        "type": "typedDict",
                                                        "propertyTypes": {
                                                            "entityName": "string",
                                                            "projectName": "string",
                                                        },
                                                    },
                                                    "value": {
                                                        "type": "typedDict",
                                                        "propertyTypes": {
                                                            "project": "project",
                                                            "filter": "string",
                                                            "order": "string",
                                                        },
                                                    },
                                                },
                                                "value": {
                                                    "type": "list",
                                                    "objectType": "run",
                                                    "maxLength": 50,
                                                },
                                            },
                                            "varName": "runs",
                                        }
                                    },
                                },
                            },
                            "key": {
                                "nodeType": "const",
                                "type": "string",
                                "val": "",
                            },
                        },
                    },
                    "__userInput": True,
                }
            }
        }


class WeavePanelArtifact(Panel):
    artifact: Optional[str] = Attr(
        json_path="spec.config.panel2Config.exp.fromOp.inputs.artifactName.val"
    )
    tab: str = Attr(
        json_path="spec.config.panel2Config.panelConfig.tabConfigs.overview.selectedTab",
        validators=[OneOf(["overview", "metadata", "usage", "files", "lineage"])],
    )

    def __init__(self, artifact, tab="overview", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spec["config"] = self._default_config()
        self.artifact = artifact
        self.tab = tab

    @classmethod
    def from_json(cls, spec):
        artifact = spec["config"]["panel2Config"]["exp"]["fromOp"]["inputs"][
            "artifactName"
        ]["val"]
        tab = spec["config"]["panel2Config"]["panelConfig"]["tabConfigs"]["overview"][
            "selectedTab"
        ]
        return cls(artifact, tab)

    @property
    def view_type(self) -> str:
        return "Weave"

    @staticmethod
    def _default_config():
        return {
            "panel2Config": {
                "exp": {
                    "nodeType": "output",
                    "type": {
                        "type": "tagged",
                        "tag": {
                            "type": "tagged",
                            "tag": {
                                "type": "typedDict",
                                "propertyTypes": {
                                    "entityName": "string",
                                    "projectName": "string",
                                },
                            },
                            "value": {
                                "type": "typedDict",
                                "propertyTypes": {
                                    "project": "project",
                                    "artifactName": "string",
                                },
                            },
                        },
                        "value": "artifact",
                    },
                    "fromOp": {
                        "name": "project-artifact",
                        "inputs": {
                            "project": {
                                "nodeType": "var",
                                "type": {
                                    "type": "tagged",
                                    "tag": {
                                        "type": "typedDict",
                                        "propertyTypes": {
                                            "entityName": "string",
                                            "projectName": "string",
                                        },
                                    },
                                    "value": "project",
                                },
                                "varName": "project",
                            },
                            "artifactName": {
                                "nodeType": "const",
                                "type": "string",
                                "val": "",
                            },
                        },
                    },
                    "__userInput": True,
                },
                "panelInputType": {
                    "type": "tagged",
                    "tag": {
                        "type": "tagged",
                        "tag": {
                            "type": "typedDict",
                            "propertyTypes": {
                                "entityName": "string",
                                "projectName": "string",
                            },
                        },
                        "value": {
                            "type": "typedDict",
                            "propertyTypes": {
                                "project": "project",
                                "artifactName": "string",
                            },
                        },
                    },
                    "value": "artifact",
                },
                "panelConfig": {
                    "tabConfigs": {"overview": {"selectedTab": "overview"}}
                },
            }
        }


class WeavePanelArtifactVersionedFile(Panel):
    artifact: str = Attr(
        json_path="spec.config.panel2Config.exp.fromOp.inputs.artifactVersion.fromOp.inputs.artifactName.val"
    )
    version: str = Attr(
        json_path="spec.config.panel2Config.exp.fromOp.inputs.artifactVersion.fromOp.inputs.artifactVersionAlias.val",
    )
    file: str = Attr(json_path="spec.config.panel2Config.exp.fromOp.inputs.path.val")

    def __init__(self, artifact, version, file, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spec["config"] = self._default_config()
        self.artifact = artifact
        self.version = version
        self.file = file

    @classmethod
    def from_json(cls, spec):
        artifact = spec["config"]["panel2Config"]["exp"]["fromOp"]["inputs"][
            "artifactVersion"
        ]["fromOp"]["inputs"]["artifactName"]["val"]
        version = spec["config"]["panel2Config"]["exp"]["fromOp"]["inputs"][
            "artifactVersion"
        ]["fromOp"]["inputs"]["artifactVersionAlias"]["val"]
        file = spec["config"]["panel2Config"]["exp"]["fromOp"]["inputs"]["path"]["val"]
        return cls(artifact, version, file)

    @property
    def view_type(self) -> str:
        return "Weave"

    @staticmethod
    def _default_config():
        return {
            "panel2Config": {
                "exp": {
                    "nodeType": "output",
                    "type": {
                        "type": "tagged",
                        "tag": {
                            "type": "tagged",
                            "tag": {
                                "type": "typedDict",
                                "propertyTypes": {
                                    "entityName": "string",
                                    "projectName": "string",
                                },
                            },
                            "value": {
                                "type": "typedDict",
                                "propertyTypes": {
                                    "project": "project",
                                    "artifactName": "string",
                                    "artifactVersionAlias": "string",
                                },
                            },
                        },
                        "value": {
                            "type": "file",
                            "extension": "json",
                            "wbObjectType": {"type": "table", "columnTypes": {}},
                        },
                    },
                    "fromOp": {
                        "name": "artifactVersion-file",
                        "inputs": {
                            "artifactVersion": {
                                "nodeType": "output",
                                "type": {
                                    "type": "tagged",
                                    "tag": {
                                        "type": "tagged",
                                        "tag": {
                                            "type": "typedDict",
                                            "propertyTypes": {
                                                "entityName": "string",
                                                "projectName": "string",
                                            },
                                        },
                                        "value": {
                                            "type": "typedDict",
                                            "propertyTypes": {
                                                "project": "project",
                                                "artifactName": "string",
                                                "artifactVersionAlias": "string",
                                            },
                                        },
                                    },
                                    "value": "artifactVersion",
                                },
                                "fromOp": {
                                    "name": "project-artifactVersion",
                                    "inputs": {
                                        "project": {
                                            "nodeType": "var",
                                            "type": {
                                                "type": "tagged",
                                                "tag": {
                                                    "type": "typedDict",
                                                    "propertyTypes": {
                                                        "entityName": "string",
                                                        "projectName": "string",
                                                    },
                                                },
                                                "value": "project",
                                            },
                                            "varName": "project",
                                        },
                                        "artifactName": {
                                            "nodeType": "const",
                                            "type": "string",
                                            "val": "",
                                        },
                                        "artifactVersionAlias": {
                                            "nodeType": "const",
                                            "type": "string",
                                            "val": "",
                                        },
                                    },
                                },
                            },
                            "path": {"nodeType": "const", "type": "string", "val": ""},
                        },
                    },
                    "__userInput": True,
                }
            }
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
    "Vega2": CustomChart,
    "Vega3": Vega3,
    "Weave": WeavePanel,
}

weave_panels = [
    WeavePanelSummaryTable,
    WeavePanelArtifactVersionedFile,
    WeavePanelArtifact,
    WeavePanel,
]
