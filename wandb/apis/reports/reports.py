import dataclasses
import inspect
import json
import re
import urllib
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import MISSING, dataclass, field
from functools import wraps
from typing import Any, Callable, List, Optional, TypeVar, Union, cast, overload

import wandb
from wandb.sdk.lib import ipython

from .mutations import CREATE_PROJECT, UPSERT_VIEW
from .util import (
    Base,
    Block,
    Panel,
    _,
    attr,
    generate_name,
    nested_get,
    nested_set,
    tuple_factory,
)
from .validators import (
    AGGFUNCS,
    CODE_COMPARE_DIFF,
    FONT_SIZES,
    LEGEND_POSITIONS,
    LINEPLOT_STYLES,
    MARKS,
    RANGEFUNCS,
    SMOOTHING_TYPES,
    Between,
    Length,
    OneOf,
    TypeValidator,
)

api = wandb.Api()


class LineKey:
    def __init__(self, key) -> None:
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


@dataclass(repr=False)
class RGBA(Base):
    r: int = attr(metadata={"validators": [Between(0, 255)]})
    g: int = attr(metadata={"validators": [Between(0, 255)]})
    b: int = attr(metadata={"validators": [Between(0, 255)]})
    a: Union[int, float] = attr(default=None, metadata={"validators": [Between(0, 1)]})

    @classmethod
    def from_json(cls, d: dict) -> "RGBA":
        color = d.get("transparentColor").replace(" ", "")
        r, g, b, a = re.split(r"\(|\)|,", color)[1:-1]
        r, g, b, a = int(r), int(g), int(b), float(a)
        return cls(r, g, b, a)

    @property
    def spec(self) -> dict:
        return {
            "color": f"rgb({self.r}, {self.g}, {self.b})",
            "transparentColor": f"rgba({self.r}, {self.g}, {self.b}, {self.a})",
        }


@dataclass(repr=False)
class LinePlot(Panel):
    title: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.chartTitle",
        },
    )
    x: Optional[str] = attr(default=None, metadata={"json_path": "spec.config.xAxis"})
    y: Optional[list] = attr(
        default=None, metadata={"json_path": "spec.config.metrics"}
    )
    range_x: Union[list, tuple] = attr(
        default_factory=tuple_factory(size=2),
        metadata={
            "json_path": ["spec.config.xAxisMin", "spec.config.xAxisMax"],
            "validators": [
                Length(2),
                TypeValidator(Optional[Union[int, float]], how="keys"),
            ],
        },
    )
    range_y: Union[list, tuple] = attr(
        default_factory=tuple_factory(size=2),
        metadata={
            "json_path": ["spec.config.yAxisMin", "spec.config.yAxisMax"],
            "validators": [
                Length(2),
                TypeValidator(Optional[Union[int, float]], how="keys"),
            ],
        },
    )
    log_x: Optional[bool] = attr(
        default=None, metadata={"json_path": "spec.config.xLogScale"}
    )
    log_y: Optional[bool] = attr(
        default=None, metadata={"json_path": "spec.config.xLogScale"}
    )
    title_x: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.xAxisTitle"}
    )
    title_y: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.yAxisTitle"}
    )
    ignore_outliers: Optional[bool] = attr(
        default=None, metadata={"json_path": "spec.config.ignoreOutliers"}
    )
    groupby: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.groupBy"}
    )
    groupby_aggfunc: Optional[str] = attr(
        default=None,
        metadata={"json_path": "spec.config.groupAgg", "validators": [OneOf(AGGFUNCS)]},
    )
    groupby_rangefunc: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.groupArea",
            "validators": [OneOf(RANGEFUNCS)],
        },
    )
    smoothing_factor: Optional[float] = attr(
        default=None, metadata={"json_path": "spec.config.smoothingWeight"}
    )
    smoothing_type: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.smoothingType",
            "validators": [OneOf(SMOOTHING_TYPES)],
        },
    )
    smoothing_show_original: Optional[bool] = attr(
        default=None, metadata={"json_path": "spec.config.showOriginalAfterSmoothing"}
    )
    max_runs_to_show: Optional[int] = attr(
        default=None, metadata={"json_path": "spec.config.smoothingType"}
    )
    custom_expressions: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.expressions"}
    )
    plot_type: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.plotType",
            "validators": [OneOf(LINEPLOT_STYLES)],
        },
    )
    font_size: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.fontSize",
            "validators": [OneOf(FONT_SIZES)],
        },
    )
    legend_position: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.legendPosition",
            "validators": [OneOf(LEGEND_POSITIONS)],
        },
    )
    legend_template: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.legendTemplate"}
    )
    # attr(default=None, metadata={"json_path": "spec.config.startingXAxis"})
    # attr(default=None, metadata={"json_path": "spec.config.useLocalSmoothing"})
    # attr(default=None, metadata={"json_path": "spec.config.useGlobalSmoothingWeight"})
    # attr(default=None, metadata={"json_path": "spec.config.legendFields"})
    aggregate: Optional[bool] = attr(
        default=None, metadata={"json_path": "spec.config.aggregate"}
    )
    # attr(default=None, metadata={"json_path": "spec.config.aggregateMetrics"})
    # attr(default=None, metadata={"json_path": "spec.config.metricRegex"})
    # attr(default=None, metadata={"json_path": "spec.config.useMetricRegex"})
    # attr(default=None, metadata={"json_path": "spec.config.yAxisAutoRange"})
    # attr(default=None, metadata={"json_path": "spec.config.groupRunsLimit"})
    xaxis_expression: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.xExpression"}
    )
    # attr(default=None, metadata={"json_path": "spec.config.colorEachMetricDifferently"})
    # attr(default=None, metadata={"json_path": "spec.config.showLegend"})

    line_titles: Optional[dict] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.overrideSeriesTitles",
            "validators": [
                TypeValidator(LineKey, how="keys"),
                TypeValidator(str, how="values"),
            ],
        },
    )
    line_marks: Optional[dict] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.overrideMarks",
            "validators": [
                TypeValidator(LineKey, how="keys"),
                OneOf(MARKS, how="values"),
            ],
        },
    )
    line_colors: Optional[dict] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.overrideColors",
            "validators": [
                TypeValidator(LineKey, how="keys"),
                TypeValidator(RGBA, how="values"),
            ],
        },
    )
    line_widths: Optional[dict] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.overrideLineWidths",
            "validators": [
                TypeValidator(LineKey, how="keys"),
                TypeValidator(Union[int, float], how="values"),
                Between(0.5, 3.0, how="values"),
            ],
        },
    )
    
    @attr(x).getter
    def _(self):
        json_path = self._get_path("x")
        value = nested_get(self, json_path)
        return self.panel_metrics_helper.back_to_front(value)

    @attr(x).setter
    def _(self, value):
        json_path = self._get_path("x")
        value = self.panel_metrics_helper.front_to_back(value)
        nested_set(self, json_path, value)
        
    @attr(y).getter
    def _(self):
        json_paths = self._get_path("y")
        value = [nested_get(self, p) for p in json_paths]
        return [self.panel_metrics_helper.back_to_front(v) for v in value]

    @attr(y).setter
    def _(self, value):
        json_paths = self._get_path("y")        
        value = [self.panel_metrics_helper.front_to_back(v) for v in value]
        for p, v in zip(json_paths, value):
            nested_set(self, p, v)

    @property
    def view_type(self):
        return "Run History Line Plot"


@dataclass(repr=False)
class ScatterPlot(Panel):
    title: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.chartTitle"}
    )
    x: Optional[str] = attr(default=None, metadata={"json_path": "spec.config.xAxis"})
    y: Optional[str] = attr(default=None, metadata={"json_path": "spec.config.yAxis"})
    z: Optional[str] = attr(default=None, metadata={"json_path": "spec.config.zAxis"})
    range_x: Union[list, tuple] = attr(
        default_factory=tuple_factory(size=2),
        metadata={
            "json_path": ["spec.config.xAxisMin", "spec.config.xAxisMax"],
            "validators": [
                Length(2),
                TypeValidator(Optional[Union[int, float]], how="keys"),
            ],
        },
    )
    range_y: Union[list, tuple] = attr(
        default_factory=tuple_factory(size=2),
        metadata={
            "json_path": ["spec.config.yAxisMin", "spec.config.yAxisMax"],
            "validators": [
                Length(2),
                TypeValidator(Optional[Union[int, float]], how="keys"),
            ],
        },
    )
    range_z: Union[list, tuple] = attr(
        default_factory=tuple_factory(size=2),
        metadata={
            "json_path": ["spec.config.zAxisMin", "spec.config.zAxisMax"],
            "validators": [
                Length(2),
                TypeValidator(Optional[Union[int, float]], how="keys"),
            ],
        },
    )
    log_x: Optional[bool] = attr(
        default=None, metadata={"json_path": "spec.config.xAxisLogScale"}
    )
    log_y: Optional[bool] = attr(
        default=None, metadata={"json_path": "spec.config.yAxisLogScale"}
    )
    log_z: Optional[bool] = attr(
        default=None, metadata={"json_path": "spec.config.zAxisLogScale"}
    )
    running_ymin: Optional[bool] = attr(
        default=None, metadata={"json_path": "spec.config.showMaxYAxisLine"}
    )
    running_ymax: Optional[bool] = attr(
        default=None, metadata={"json_path": "spec.config.showMinYAxisLine"}
    )
    running_ymean: Optional[bool] = attr(
        default=None, metadata={"json_path": "spec.config.showAvgYAxisLine"}
    )
    legend_template: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.legendTemplate"}
    )
    gradient: Optional[dict] = attr(
        default_factory=dict,
        metadata={
            "json_path": "spec.config.customGradient",
            "validators": [TypeValidator(RGBA, how="values")],
        },
    )
    # color: ... = attr(default=None, metadata={"json_path":"spec.config.color"})
    # range_color: ... = attr(default=None,
    #     ["spec.config.minColor", "spec.config.maxColor"],
    #     (list, tuple),
    #     "validators":[Length(2), TypeValidator((int, float), how='keys')],
    # )

    # attr(default=None, metadata={"json_path":"spec.config.legendFields"})
    font_size: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.fontSize",
            "validators": [OneOf(FONT_SIZES)],
        },
    )
    # attr(default=None, metadata={"json_path":"spec.config.yAxisLineSmoothingWeight"})
    regression: Optional[bool] = attr(default=None, metadata={'json_path': 'spec.config.showLinearRegression'})
    
    # @attr(x).getter
    # def _(self):
    #     json_path = self._get_path("x")
    #     value = nested_get(self, json_path)
    #     return self.panel_metrics_helper.scatter_back_to_front(value)

    # @attr(x).setter
    # def _(self, value):
    #     json_path = self._get_path("x")
    #     value = self.panel_metrics_helper.scatter_front_to_back(value)
    #     nested_set(self, json_path, value)
        
    # @attr(y).getter
    # def _(self):
    #     json_path = self._get_path("y")
    #     value = nested_get(self, json_path)
    #     return self.panel_metrics_helper.scatter_back_to_front(value)

    # @attr(y).setter
    # def _(self, value):
    #     json_path = self._get_path("y")
    #     value = self.panel_metrics_helper.scatter_front_to_back(value)
    #     nested_set(self, json_path, value)
        
    # @attr(z).getter
    # def _(self):
    #     json_path = self._get_path("z")
    #     value = nested_get(self, json_path)
    #     return self.panel_metrics_helper.scatter_back_to_front(value)

    # @attr(z).setter
    # def _(self, value):
    #     json_path = self._get_path("z")
    #     value = self.panel_metrics_helper.scatter_front_to_back(value)
    #     nested_set(self, json_path, value)

    @property
    def view_type(self) -> str:
        return "Scatter Plot"


@dataclass(repr=False)
class BarPlot(Panel):
    title: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.chartTitle"}
    )
    metrics: Optional[list] = attr(
        default_factory=list,
        metadata={
            "json_path": "spec.config.metrics",
            "validators": [TypeValidator(str, how="keys")],
        },
    )
    vertical: Optional[bool] = attr(
        default=None, metadata={"json_path": "spec.config.vertical"}
    )
    range_x: Union[list, tuple] = attr(
        default_factory=tuple_factory(size=2),
        metadata={
            "json_path": ["spec.config.xAxisMin", "spec.config.xAxisMax"],
            "validators": [
                Length(2),
                TypeValidator(Optional[Union[int, float]], how="keys"),
            ],
        },
    )
    title_x: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.xAxisTitle"}
    )
    title_y: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.yAxisTitle"}
    )
    groupby: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.groupBy"}
    )
    groupby_aggfunc: Optional[str] = attr(
        default=None,
        metadata={"json_path": "spec.config.groupAgg", "validators": [OneOf(AGGFUNCS)]},
    )
    groupby_rangefunc: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.groupArea",
            "validators": [OneOf(RANGEFUNCS)],
        },
    )
    max_runs_to_show: Optional[int] = attr(
        default=None, metadata={"json_path": "spec.config.limit"}
    )
    max_bars_to_show: Optional[int] = attr(
        default=None, metadata={"json_path": "spec.config.barLimit"}
    )
    custom_expressions: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.expressions"}
    )
    legend_template: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.legendTemplate"}
    )
    font_size: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.fontSize",
            "validators": [OneOf(FONT_SIZES)],
        },
    )
    # attr(default=None, metadata={"json_path":"spec.config.limit"})
    # attr(default=None, metadata={"json_path":"spec.config.barLimit"})
    # attr(default=None, metadata={"json_path":"spec.config.aggregate"})
    # attr(default=None, metadata={"json_path":"spec.config.aggregateMetrics"})
    # attr(default=None, metadata={"json_path":"spec.config.groupRunsLimit"})
    # attr(default=None, metadata={"json_path":"spec.config.plotStyle"})
    # attr(default=None, metadata={"json_path":"spec.config.legendFields"})
    # attr(default=None, metadata={"json_path":"spec.config.colorEachMetricDifferently"})

    line_titles: Optional[dict] = attr(
        default_factory=dict,
        metadata={
            "json_path": "spec.config.overrideSeriesTitles",
            "validators": [
                TypeValidator(LineKey, how="keys"),
                TypeValidator(str, how="values"),
            ],
        },
    )
    line_colors: Optional[dict] = attr(
        default_factory=dict,
        metadata={
            "json_path": "spec.config.overrideColors",
            "validators": [
                TypeValidator(LineKey, how="keys"),
                TypeValidator(RGBA, how="values"),
            ],
        },
    )

    @attr(metrics).getter
    def _(self):
        json_paths = self._get_path("metrics")
        value = [nested_get(self, p) for p in json_paths]
        return [self.panel_metrics_helper.back_to_front(v) for v in value]

    @attr(metrics).setter
    def _(self, value):
        json_paths = self._get_path("metrics")
        value = [self.panel_metrics_helper.front_to_back(v) for v in value]
        for p, v in zip(json_paths, value):
            nested_set(self, p, v)


    @property
    def view_type(self) -> str:
        return "Bar Chart"


@dataclass(repr=False)
class ScalarChart(Panel):
    title: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.chartTitle"}
    )
    metric: str = attr(default="", metadata={"json_path": "spec.config.metrics"})
    groupby_aggfunc: Optional[str] = attr(
        default=None,
        metadata={"json_path": "spec.config.groupAgg", "validators": [OneOf(AGGFUNCS)]},
    )
    groupby_rangefunc: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.groupArea",
            "validators": [OneOf(RANGEFUNCS)],
        },
    )
    custom_expressions: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.expressions"}
    )
    legend_template: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.legendTemplate"}
    )

    # attr(metadata={"json_path": "spec.config.aggregate"})
    # attr(metadata={"json_path": "spec.config.aggregateMetrics"})
    # attr(metadata={"json_path": "spec.config.groupBy"})
    # attr(metadata={"json_path": "spec.config.groupRunsLimit"})
    # attr(metadata={"json_path": "spec.config.legendFields"})
    # attr(metadata={"json_path": "spec.config.showLegend"})
    font_size: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.fontSize",
            "validators": [OneOf(FONT_SIZES)],
        },
    )

    @attr(metric).getter
    def _(self):
        json_path = self._get_path("metric")
        value = nested_get(self, json_path)[0]
        return self.panel_metrics_helper.back_to_front(value)

    @attr(metric).setter
    def _(self, new_metrics):
        json_path = self._get_path("metric")
        new_metrics = self.panel_metrics_helper.front_to_back(new_metrics)
        nested_set(self, json_path, [new_metrics])


    @property
    def view_type(self) -> str:
        return "Scalar Chart"


@dataclass(repr=False)
class CodeComparer(Panel):
    diff: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.diff",
            "validators": [OneOf(CODE_COMPARE_DIFF)],
        },
    )

    @property
    def view_type(self) -> str:
        return "Code Comparer"


@dataclass(repr=False)
class PCColumn(Base):
    metric: str = attr(metadata={"json_path": "spec.accessor"})
    name: Optional[str] = attr(default=None, metadata={"json_path": "spec.displayName"})
    ascending: Optional[bool] = attr(default=None, metadata={"json_path": "spec.inverted"})
    log_scale: Optional[bool] = attr(default=None, metadata={"json_path": "spec.log"})
    
    @classmethod
    def from_json(cls, spec):
        obj = cls(metric=spec['accessor'])
        obj._spec = spec
        return obj

@dataclass(repr=False)
class ParallelCoordinatesPlot(Panel):
    columns: list = attr(
        default_factory=list, metadata={"json_path": "spec.config.columns", 'validators': [TypeValidator(PCColumn, how='keys')]}
    )
    title: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.chartTitle"}
    )

    # attr(metadata={"json_path": "spec.config.dimensions"})
    # attr(metadata={"json_path": "spec.config.customGradient"})
    # attr(metadata={"json_path": "spec.config.gradientColor"})
    # attr(metadata={"json_path": "spec.config.legendFields"})
    font_size: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.fontSize",
            "validators": [OneOf(FONT_SIZES)],
        },
    )

    @attr(columns).getter
    def _(self):
        json_path = self._get_path('columns')
        specs = nested_get(self, json_path)
        return [PCColumn.from_json(cspec) for cspec in specs]

    @attr(columns).setter
    def _(self, new_columns):
        json_path = self._get_path("columns")
        specs = [c.spec for c in new_columns]
        nested_set(self, json_path, specs)
        

        
    @property
    def view_type(self) -> str:
        return "Parallel Coordinates Plot"


@dataclass(repr=False)
class ParameterImportancePlot(Panel):
    with_respect_to: str = attr(
        default="Created Timestamp", metadata={"json_path": "spec.config.targetKey"}
    )
    
    @attr(with_respect_to).getter
    def _(self):
        json_path = self._get_path("with_respect_to")
        value = nested_get(self, json_path)
        return self.panel_metrics_helper.back_to_front(value)

    @attr(with_respect_to).setter
    def _(self, value):
        json_path = self._get_path("with_respect_to")
        value = self.panel_metrics_helper.front_to_back(value)
        nested_set(self, json_path, value)

    @property
    def view_type(self) -> str:
        return "Parameter Importance"


@dataclass(repr=False)
class RunComparer(Panel):
    diff_only: Optional[str] = attr(
        default=None,
        metadata={
            "json_path": "spec.config.diffOnly",
            "validators": [OneOf(["split", None])],
        },
    )

    @property
    def view_type(self) -> str:
        return "Run Comparer"


@dataclass(repr=False)
class MediaBrowser(Panel):
    num_columns: Optional[int] = attr(
        default=None, metadata={"json_path": "spec.config.columnCount"}
    )
    media_keys: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.media_keys"}
    )

    # attr(metadata={"json_path": "spec.config.chartTitle"})
    # attr(metadata={"json_path": "spec.config.stepIndex"})
    # attr(metadata={"json_path": "spec.config.mediaIndex"})
    # attr(metadata={"json_path": "spec.config.actualSize"})
    # attr(metadata={"json_path": "spec.config.fitToDimension"})
    # attr(metadata={"json_path": "spec.config.pixelated"})
    # attr(metadata={"json_path": "spec.config.mode"})
    # attr(metadata={"json_path": "spec.config.gallerySettings"})
    # attr(metadata={"json_path": "spec.config.gridSettings"})
    # attr(metadata={"json_path": "spec.config.selection"})
    # attr(metadata={"json_path": "spec.config.page"})
    # attr(metadata={"json_path": "spec.config.tileLayout"})
    # attr(metadata={"json_path": "spec.config.stepStrideLength"})
    # attr(metadata={"json_path": "spec.config.snapToExistingStep"})
    # attr(metadata={"json_path": "spec.config.maxGalleryItems"})
    # attr(metadata={"json_path": "spec.config.maxYAxisCount"})
    # attr(metadata={"json_path": "spec.config.moleculeConfig"})
    # attr(metadata={"json_path": "spec.config.segmentationMaskConfig"})
    # attr(metadata={"json_path": "spec.config.boundingBoxConfig"})

    @property
    def view_type(self) -> str:
        return "Media Browser"


@dataclass(repr=False)
class MarkdownPanel(Panel):
    markdown: Optional[str] = attr(
        default=None, metadata={"json_path": "spec.config.value"}
    )

    @property
    def view_type(self) -> str:
        return "Markdown Panel"


@dataclass(repr=False)
class ConfusionMatrix(Panel):
    @property
    def view_type(self) -> str:
        return "Confusion Matrix"


@dataclass(repr=False)
class DataFrames(Panel):
    @property
    def view_type(self) -> str:
        return "Data Frame Table"


@dataclass(repr=False)
class MultiRunTable(Panel):
    @property
    def view_type(self) -> str:
        return "Multi Run Table"


@dataclass(repr=False)
class Vega(Panel):
    @property
    def view_type(self) -> str:
        return "Vega"


@dataclass(repr=False)
class Vega2(Panel):
    @property
    def view_type(self) -> str:
        return "Vega2"


@dataclass(repr=False)
class Vega3(Panel):
    @property
    def view_type(self) -> str:
        return "Vega3"


@dataclass(repr=False)
class WeavePanel(Panel):
    @property
    def view_type(self) -> str:
        return "Weave"


@dataclass(repr=False)
class InlineLaTeX(Block):
    latex: str = attr()

    @property
    def spec(self) -> dict:
        return {"type": "latex", "children": [{"text": ""}], "content": self.latex}


@dataclass(repr=False)
class InlineCode(Block):
    code: str = attr()

    @property
    def spec(self) -> dict:
        return {"text": self.code, "inlineCode": True}


@dataclass(repr=False)
class P(Block):
    text: Union[str, InlineLaTeX, InlineCode, list] = attr()

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


def _default_runsets():
    return [RunSet()]


@dataclass(repr=False)
class PanelGrid(Block):
    """
    Panel grids are containers for panels and runsets.
    Each panel grid may contain multiple panels and multiple runsets.
    The runsets determine what data available to visualize, and the panels will try to visualize that data.
    https://docs.wandb.ai/guides/reports/reports-walkthrough#panel-grids
    """

    runsets: list = attr(
        default_factory=_default_runsets,
        metadata={"json_path": "spec.metadata.runSets"},
    )
    panels: list = attr(
        default_factory=list,
        metadata={"json_path": "spec.metadata.panelBankSectionConfig.panels"},
    )

    @attr(panels).getter
    def _(self):
        json_path = self._get_path("panels")
        specs = nested_get(self, json_path)
        panels = []
        for pspec in specs:
            cls = panel_mapping[pspec["viewType"]]
            panels.append(cls.from_json(pspec))
        return panels

    @attr(panels).setter
    def _(self, new_panels):
        json_path = self._get_path("panels")

        # For PC and Scatter, we need to use more specific values, so update if possible.
        # This only happens on set, and only when assigned to a panel grid because that is
        # the earliest time that we have a runset to check what kind of metric is being assigned
        new_panels = self._get_specific_keys_for_certain_plots(new_panels, setting=True)

        new_specs = [p.spec for p in new_panels]
        nested_set(self, json_path, new_specs)

    @attr(runsets).getter
    def _(self):
        json_path = self._get_path("runsets")
        specs = nested_get(self, json_path)
        return [RunSet.from_json(spec) for spec in specs]

    @attr(runsets).setter
    def _(self, new_runsets):
        json_path = self._get_path("runsets")
        new_specs = [rs.spec for rs in new_runsets]
        nested_set(self, json_path, new_specs)

    def _get_specific_keys_for_certain_plots(self, panels, setting=False):
        """
        Helper function to map names for certain plots
        """
        gen = self.runsets[0].pm_query_generator
        transform = gen.front_to_back if setting else gen.back_to_front
        for p in panels:
            if isinstance(p, ScatterPlot):
                for param in ["x", "y", "z"]:
                    value = getattr(p, param)
                    if (
                        value is not None
                        and (not value.startswith(".config") and not ".value" in value)
                        and not value.startswith("summary_metrics.")
                    ):
                        setattr(p, param, transform(value))
            elif isinstance(p, ParallelCoordinatesPlot):
                if p.columns:
                    for col in p.columns:
                        col.metric = transform(col.metric)
        return panels

    def __new__(cls, *args, **kwargs):
        def _generate_default_panel_grid_spec():
            return {
                "type": "panel-grid",
                "children": [{"text": ""}],
                "metadata": {
                    "openViz": True,
                    "panels": {
                        "views": {
                            "0": {"name": "Panels", "defaults": [], "config": []}
                        },
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

        obj = super().__new__(cls)
        obj._spec = _generate_default_panel_grid_spec()
        return obj


def _default_filters():
    return {"$or": [{"$and": []}]}


def _default_groupby():
    return []


def _default_order():
    return ["-CreatedTimestamp"]


@dataclass(repr=False)
class RunSet(Base):
    """
    Run sets are a collection of runs from a particular entity and project.
    The run set supports filtering, grouping, and ordering, similar to a SQL Table or DataFrame.
    https://docs.wandb.ai/guides/reports/reports-walkthrough#run-sets
    """

    entity: str = attr(
        default=api.default_entity, metadata={"json_path": "spec.project.entityName"}
    )
    project: str = attr(default="", metadata={"json_path": "spec.project.name"})
    name: str = attr(default="Run set", metadata={"json_path": "spec.name"})
    query: str = attr(default="", metadata={"json_path": "spec.search.query"})
    filters: str = attr(
        default_factory=_default_filters, metadata={"json_path": "spec.filters"}
    )
    groupby: str = attr(
        default_factory=_default_groupby, metadata={"json_path": "spec.grouping"}
    )
    order: str = attr(
        default_factory=_default_order, metadata={"json_path": "spec.sort"}
    )

    def __new__(cls, *args, **kwargs):
        def _generate_default_runset_spec():
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

        obj = super().__new__(cls)
        obj._spec = _generate_default_runset_spec()
        obj.query_generator = wandb.apis.public.QueryGenerator()
        obj.pm_query_generator = wandb.apis.public.PythonMongoishQueryGenerator(obj)
        return obj

    @attr(filters).getter
    def _(self):
        json_path = self._get_path("filters")
        filter_specs = nested_get(self, json_path)
        return self.query_generator.filter_to_mongo(filter_specs)

    @attr(filters).setter
    def _(self, new_filters):
        json_path = self._get_path("filters")
        new_filter_specs = self.query_generator.mongo_to_filter(new_filters)
        nested_set(self, json_path, new_filter_specs)

    def set_filters_with_python_expr(self, expr: str) -> None:
        """
        Helper function to make it easier to set filters using simple python expressions.
        Syntax is similar to pandas `DataFrame.query` function.

        Some examples you can do:
        - x > 0 and x <= 10
        - User == "Andrew"
        - State != "Failed"
        - Hyperparameter in ["alpha", "beta"]
        """
        self.filters = self.pm_query_generator.python_to_mongo(expr)
        return self

    @attr(groupby).getter
    def _(self):
        json_path = self._get_path("groupby")
        groupby_specs = nested_get(self, json_path)
        cols = [self.query_generator.key_to_server_path(k) for k in groupby_specs]
        return [self.pm_query_generator.back_to_front(c) for c in cols]

    @attr(groupby).setter
    def _(self, new_groupby):
        json_path = self._get_path("groupby")
        cols = [self.pm_query_generator.front_to_back(g) for g in new_groupby]
        new_groupby_specs = [self.query_generator.server_path_to_key(c) for c in cols]
        nested_set(self, json_path, new_groupby_specs)

    @attr(order).getter
    def _(self):
        json_path = self._get_path("order")
        order_specs = nested_get(self, json_path)
        cols = self.query_generator.keys_to_order(order_specs)
        return [c[0] + self.pm_query_generator.back_to_front(c[1:]) for c in cols]

    @attr(order).setter
    def _(self, new_orders):
        json_path = self._get_path("order")
        cols = [o[0] + self.pm_query_generator.front_to_back(o[1:]) for o in new_orders]
        new_order_specs = self.query_generator.order_to_keys(cols)
        nested_set(self, json_path, new_order_specs)

    @property
    def _runs_config(self) -> dict:
        return {k: v for run in self.runs for k, v in run.config.items()}

    @property
    def runs(self) -> wandb.apis.public.Runs:
        return wandb.apis.public.Runs(api.client, self.entity, self.project)


@dataclass(repr=False)
class Report(Base):
    project: str = attr(metadata={"json_path": "viewspec.project.name"})
    entity: str = attr(
        default=api.default_entity,
        metadata={"json_path": "viewspec.project.entityName"},
    )
    title: str = attr(
        default="Untitled Report", metadata={"json_path": "viewspec.displayName"}
    )
    description: str = attr(default="", metadata={"json_path": "viewspec.description"})
    width: str = attr(default="readable", metadata={"json_path": "viewspec.spec.width"})
    blocks: list = attr(default_factory=list, metadata={"json_path": "spec.blocks"})

    def __new__(cls, *args, **kwargs):
        def _generate_default_viewspec():
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

        obj = super().__new__(cls)
        obj._viewspec = _generate_default_viewspec()
        obj._orig_viewspec = deepcopy(obj._viewspec)
        return obj

    @classmethod
    def from_json(cls, viewspec):
        obj = cls(project=viewspec["project"]["name"])
        obj._viewspec = viewspec
        obj._orig_viewspec = deepcopy(obj._viewspec)
        return obj

    @attr(blocks).getter
    def _(self):
        json_path = self._get_path("blocks")
        block_specs = nested_get(self, json_path)
        blocks = []
        for b in block_specs:
            cls = block_mapping[b["type"]]
            blocks.append(cls.from_json(b))
        return blocks[1:-1]  # accounts for hidden p blocks

    @attr(blocks).setter
    def _(self, new_blocks):
        json_path = self._get_path("blocks")
        new_block_specs = [P('').spec] + [b.spec for b in new_blocks] + [P('').spec]  # hidden p blocks
        nested_set(self, json_path, new_block_specs)

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
        return api.client

    @property
    def id(self) -> str:
        return self._viewspec["id"]

    @property
    def name(self) -> str:
        return self._viewspec["name"]

    @property
    def panel_grids(self) -> "List[PanelGrid]":
        return [b for b in self.blocks if isinstance(b, PanelGrid)]

    @property
    def runsets(self) -> "List[RunSet]":
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
                # "createdUsing": "WANDB_SDK",
                "spec": json.dumps(self.spec),
            },
        )

        viewspec = r["upsertView"]["view"]
        viewspec["spec"] = json.loads(viewspec["spec"])
        if clone:
            return Report.from_viewspec(viewspec)
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


block_mapping = {
    # "block-quote": BlockQuote,
    # "callout-block": CalloutBlock,
    # "code-block": CodeBlock,
    # "gallery": Gallery,
    # "heading": Heading,
    # "horizontal-rule": HorizontalRule,
    # "image": Image,
    # "latex": LaTeXBlock,
    # "list": List,
    # "markdown-block": MarkdownBlock,
    "panel-grid": PanelGrid,
    "paragraph": P,
    # "table-of-contents": TableOfContents,
    # "weave-panel": WeaveBlock,
    # "video": Video,
    # "spotify": Spotify,
    # "twitter": Twitter,
    # "soundcloud": SoundCloud,
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
