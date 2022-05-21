from abc import ABC
from dataclasses import dataclass
from typing import Union, List, Dict, Optional
from .helpers import delegates


# class Panel(ABC):
#     _viewType = None

#     def __init__(self, panel_grid=None, spec=None):
#         self.panel_grid = panel_grid
#         self.spec = spec or self.__generate_default_panel_spec()
#         self._update_config()

#     def __repr__(self):
#         return f"Panel: {self.spec['viewType']}"

#     def __generate_default_panel_spec(self):
#         return {
#             "viewType": None,
#             "config": {},
#         }

#     def _update_config(self):
#         self.spec["viewType"] = self._viewType
#         for key, value in self.__dict__.items():
#             self.spec["config"][key] = value


# @dataclass
# class LinePlot(Panel):
#     # Need to rename some of these options to something more sensible to end user
#     # Feels like we should follow the plotly options?
#     # Where do we put the ts interface to python option mapping?
#     # might want to ship v0 report editing before doing panels...

#     # Maybe...
#     # x: xAxis
#     # y: metrics?
#     # color: overrideColors (hex or rgb)
#     # line_dash: overrideMarks
#     # line_width: overrideLineWidths
#     # legend_titles: overrideSeriesTitles
#     # log_x: xLogScale,
#     # log_y: yLogScale,
#     # range_x: [xAxisMin, xAxisMax],
#     # range_y: [yAxisMin, yAxisMax]
#     # title: chartTitle,
#     # legend_position: legendPosition
#     # font_size: fontSize

#     # chartType is actually subclass?

#     xLogScale: Optional[bool] = None
#     yLogScale: Optional[bool] = None
#     xAxis: Optional[str] = None
#     startingXAxis: Optional[str] = None
#     smoothingWeight: Optional[float] = None
#     smoothingType: Optional[str] = None
#     useLocalSmoothing: Optional[bool] = None
#     useGlobalSmoothingWeight: Optional[bool] = None
#     ignoreOutliers: Optional[bool] = None
#     showOriginalAfterSmoothing: Optional[bool] = None
#     xAxisMin: Optional[float] = None
#     xAxisMax: Optional[float] = None
#     yAxisMin: Optional[float] = None
#     yAxisMax: Optional[float] = None
#     legendFields: Optional[List[str]] = None
#     legendTemplate: Optional[str] = None
#     aggregate: Optional[bool] = None
#     aggregateMetrics: Optional[bool] = None
#     groupBy: Optional[str] = None
#     metrics: Optional[List[str]] = None
#     metricRegex: Optional[str] = None
#     useMetricRegex: Optional[bool] = None
#     yAxisAutoRange: Optional[bool] = None
#     chartTitle: Optional[str] = None
#     xAxisTitle: Optional[str] = None
#     yAxisTitle: Optional[str] = None
#     limit: Optional[float] = None
#     groupRunsLimit: Optional[float] = None
#     expressions: Optional[List[str]] = None
#     xExpression: Optional[str] = None
#     plotType: Optional[str] = None
#     groupAgg: Optional[str] = None
#     groupArea: Optional[str] = None
#     colorEachMetricDifferently: Optional[bool] = None
#     overrideSeriesTitles: Optional[Dict[str, str]] = None
#     overrideColors: Optional[Dict[str, str]] = None
#     overrideMarks: Optional[Dict[str, str]] = None
#     overrideLineWidths: Optional[Dict[str, str]] = None
#     showLegend: Optional[bool] = None
#     legendPosition: Optional[str] = None
#     fontSize: Optional[float] = None

#     _viewType = "Run History Line Plot"

#     def __post_init__(self):
#         super().__init__()

#     def __repr__(self):
#         supplied_kws = [
#             f"{key}={value!r}"
#             for key, value in self.__dict__.items()
#             if value is not None and key not in ("spec", "_viewType")
#         ]
#         # return super().__repr__() + " " + ", ".join(supplied_kws)
#         return "{}({})".format(type(self).__name__, ", ".join(supplied_kws))
#         # return "{}({})".format(super().__repr__(), ", ".join(supplied_kws))


# @delegates()
# class StackedAreaPlot(LinePlot):
#     # Actually the same as LinePlot with plotType: 'stacked-area'
#     def __init__(self, plotType="stacked-area", **kwargs):
#         super().__init__(plotType=plotType, **kwargs)


# @delegates()
# class PercentAreaPlot(LinePlot):
#     # Actually the same as LinePlot with plotType: 'stacked-area'
#     pass


# # class StackedAreaPlot(Panel):
# #     # Actually the same as LinePlot with plotType: 'stacked-area'
# #     pass

# # class PercentAreaPlot(Panel):
# #     # Actually the same as LinePlot with plotType: 'stacked-area'
# #     pass


# # @dataclass
# # class LinePlot(Panel):
# #     y: str
# #     x: str = None

# #     def __post_init__(self):
# #         super().__init__()
# #         self.spec["config"]["metrics"] = [self.y]
# #         if self.x:
# #             self.spec["config"]["xAxis"] = self.x


# # class LinePlot(Panel):
# #     def __init__(self, y:str, x:str=None):
# #         super().__init__()
# #         self.y = y
# #         self.x = x

# #         self.spec['config']['metrics'] = [self.y]
# #         if self.x:
# #             self.spec["config"]["xAxis"] = self.x


# # class


# # @dataclass
# # class BarPlot(Panel):
# #     x: Union[str, list]

# #     def __post_init__(self):
# #         if not isinstance(x, list):
# #             x = [x]
# #         self.spec["config"]["metrics"] = self.x


# # class BarChart(Panel):
# #     def __init__(self, x):
# #         self.spec["config"]["metrics"] = [x]
# #         super().__init__()


# @dataclass
# class ScatterChart(Panel):
#     x: str
#     y: str

#     def __post_init__(self):
#         self.spec["config"]["xAxis"] = self.x
#         self.spec["config"]["yAxis"] = self.y


# @dataclass
# class ScalarChart(Panel):
#     metric: str

#     def __post_init__(self):
#         self.spec["config"]["metrics"] = [self.metric]


# @dataclass
# class MarkdownPanel(Panel):
#     value: str

#     def __post_init__(self):
#         self.spec["config"]["value"] = self.value


### alternate interfaces down here


# @dataclass
# class Panel:
#     _viewType: str = None
#     xLogScale: Optional[bool] = None
#     yLogScale: Optional[bool] = None
#     xAxis: Optional[str] = None
#     startingXAxis: Optional[str] = None
#     smoothingWeight: Optional[float] = None
#     smoothingType: Optional[str] = None
#     useLocalSmoothing: Optional[bool] = None
#     useGlobalSmoothingWeight: Optional[bool] = None
#     ignoreOutliers: Optional[bool] = None
#     showOriginalAfterSmoothing: Optional[bool] = None


#     def __init__(self, panel_grid=None, spec=None):
#         self.panel_grid = panel_grid
#         self.spec = spec or self.__generate_default_panel_spec()
#         self._update_config()

#     def __repr__(self):
#         return f"Panel: {self.spec['viewType']}"

#     def __generate_default_panel_spec(self):
#         return {
#             "viewType": None,
#             "config": {},
#         }

#     def _update_config(self):
#         self.spec["viewType"] = self._viewType
#         for key, value in self.__dict__.items():
#             self.spec["config"][key] = value


# @delegates()
# class LinePlot(Panel):
#     def __init__(self, **kwargs):
#         super().__init__(**kwargs)
