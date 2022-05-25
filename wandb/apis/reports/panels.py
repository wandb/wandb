from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Tuple, Union, List, Dict, Optional
from .blocks import PanelGrid
from .helpers import generate_name


class Panel(ABC):
    def __init__(self, panel_grid: PanelGrid = None, spec: dict = None):
        self.panel_grid = panel_grid
        self._spec = spec or self.__generate_default_panel_spec()
        for setting, value in self._valid_settings.items():
            self._spec["config"][setting] = value

    _attr_json_mapping = {}

    @classmethod
    def from_json(cls, spec):
        attrs = {}
        for attr, json_key in cls._attr_json_mapping.items():
            if isinstance(json_key, str):
                attrs[attr] = spec["config"].get(json_key)
            elif isinstance(json_key, list):
                attrs[attr] = [spec["config"].get(key) for key in json_key]

        obj = cls(**attrs)
        obj._spec = spec
        return obj

    @property
    def spec(self):
        for attr, json_key in self._attr_json_mapping.items():
            attr_value = getattr(self, attr)
            if not self._isNone(attr_value):
                if isinstance(json_key, str):
                    self._spec["config"][json_key] = attr_value
                elif isinstance(json_key, list):
                    for i, key in enumerate(json_key):
                        self._spec["config"][key] = attr_value[i]
        return self._spec

    def __repr__(self):
        _class = self.__class__.__name__
        _settings = [f"{k}={v!r}" for k, v in self._valid_settings.items()]
        return "{}({})".format(_class, ", ".join(_settings))

    def __generate_default_panel_spec(self):
        return {
            # "__id__": generate_name(),
            "viewType": None,
            "config": {},
            # "ref": None,
            # "layout": None,
        }

    @staticmethod
    def _isNone(x):
        if isinstance(x, (list, tuple)):
            return all(v is None for v in x)
        else:
            return x is None

    @property
    def _valid_settings(self):
        return {
            k: v
            for k, v in self.__dict__.items()
            if k not in {"panel_grid", "spec", "_spec"} and not self._isNone(v)
        }

    @property
    def view_type(self):
        return self.spec["viewType"]


@dataclass(repr=False)
class ParallelCoordinatesPanel(Panel):
    columns: list = None  # columns: list = None
    title: list = None  # chartTitle: str = None
    # customGradient: dict = None
    # gradientColor: bool = None
    # legendFields: list = None
    # dimensions: str = None
    # fontSize: str = None
    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {"columns": "columns", "title": "chartTitle"}


@dataclass(repr=False)
class WeavePanel(Panel):
    panel2Config: dict = None

    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {"panel2Config": "panel2Config"}


@dataclass(repr=False)
class LinePlotPanel(Panel):
    # aggregate: bool = None
    # aggregateMetrics: bool = None
    title: str = None  # chartTitle: str = None
    # colorEachMetricDifferently: bool = None
    # expressions: list = None
    # fontSize: dict = None  # {'$ref': '#/definitions/PlotFontSizeOrAuto'}
    # groupAgg: dict = None  # {'$ref': '#/definitions/ChartAggOption'}
    # groupArea: dict = None  # {'$ref': '#/definitions/ChartAreaOption'}
    # groupBy: str = None
    # groupRunsLimit: float = None
    # ignoreOutliers: bool = None
    # legendFields: list = None
    # legendPosition: dict = None  # {'$ref': '#/definitions/LegendPosition'}
    # legendTemplate: str = None
    # limit: float = None
    # metricRegex: str = None
    y: List[str] = None  # metrics: list = None
    # overrideColors: dict = None  # {'additionalProperties': {'additionalProperties': False, 'properties': {'color': {'type': 'string'}, 'transparentColor': {'type': 'string'}}, 'required': ['color', 'transparentColor'], 'type': 'object'}, 'type': 'object'}
    # overrideLineWidths: dict = (
    #     None  # {'additionalProperties': {'type': 'number'}, 'type': 'object'}
    # )
    # overrideMarks: dict = None  # {'additionalProperties': {'$ref': '#/definitions/Mark'}, 'type': 'object'}
    # overrideSeriesTitles: dict = (
    #     None  # {'additionalProperties': {'type': 'string'}, 'type': 'object'}
    # )
    # plotType: dict = None  # {'$ref': '#/definitions/PlotType'}
    # showLegend: bool = None
    # showOriginalAfterSmoothing: bool = None
    # smoothingType: dict = None  # {'$ref': '#/definitions/SmoothingType'}
    # smoothingWeight: float = None
    # startingXAxis: str = None
    # useGlobalSmoothingWeight: bool = None
    # useLocalSmoothing: bool = None
    # useMetricRegex: bool = None
    x: str = None  # xAxis: str = None
    range_x: Tuple[float, float] = None
    range_y: Tuple[float, float] = None
    log_x: bool = None
    log_y: bool = None

    # xAxisMax: float = None
    # xAxisMin: float = None
    # xAxisTitle: str = None
    # xExpression: str = None
    # xLogScale: bool = None
    # yAxisAutoRange: bool = None
    # yAxisMax: float = None
    # yAxisMin: float = None
    # yAxisTitle: str = None
    # yLogScale: bool = None

    def __post_init__(self):
        super().__init__()
        self._spec["viewType"] = "Run History Line Plot"

    _attr_json_mapping = {
        "title": "chartTitle",
        "y": "metrics",
        "x": "xAxis",
        "range_x": ["xAxisMin", "xAxisMax"],
        "range_y": ["yAxisMin", "yAxisMax"],
        "log_x": "xLogScale",
        "log_y": "yLogScale",
    }

    # settings = {
    #     k: v
    #     for k, v in locals().items()
    #     if k not in ("cls", "spec", "conf") and not cls._isNone(v)
    # }

    # obj = cls(**settings)
    # obj._spec = spec
    # return obj
    # # # return cls(**spec["config"])


@dataclass(repr=False)
class BarPlotPanel(Panel):
    aggregate: bool = None  # aggregate: bool = None
    # aggregateMetrics: bool = None
    # barLimit: float = None
    title: str = None  # chartTitle: str = None
    # colorEachMetricDifferently: bool = None
    # expressions: list = None
    # fontSize: dict = None  # {'$ref': '#/definitions/PlotFontSizeOrAuto'}
    # groupAgg: dict = None  # {'$ref': '#/definitions/ChartAggOption'}
    # groupArea: dict = None  # {'$ref': '#/definitions/ChartAreaOption'}
    # groupBy: str = None
    # groupRunsLimit: float = None
    # legendFields: list = None
    # legendTemplate: str = None
    # limit: float = None
    y: list = None  # metrics: list = None
    # overrideColors: dict = None  # {'additionalProperties': {'additionalProperties': False, 'properties': {'color': {'type': 'string'}, 'transparentColor': {'type': 'string'}}, 'required': ['color', 'transparentColor'], 'type': 'object'}, 'type': 'object'}
    # overrideSeriesTitles: dict = (
    #     None  # {'additionalProperties': {'type': 'string'}, 'type': 'object'}
    # )
    # plotStyle: dict = None  # {'$ref': '#/definitions/PlotStyle'}
    vertical: bool = None  # vertical: bool = None
    range_x: list = None
    range_y: list = None
    # xAxisMax: float = None
    # xAxisMin: float = None
    # xAxisTitle: str = None
    # yAxisTitle: str = None

    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {
        "aggregate": "aggregate",
        "title": "chartTitle",
        "y": "metrics",
        "vertical": "vertical",
        "range_x": ["xAxisMin", "xAxisMax"],
        "range_y": ["yAxisMin", "yAxisMax"],
    }


@dataclass(repr=False)
class CodeComparerPanel(Panel):
    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {}


@dataclass(repr=False)
class ConfusionMatrixPanel(Panel):
    # dataFrameKey: str = None
    # normalizeClasses: bool = None
    # popupColumn: str = None
    # predictedClassColumn: str = None
    # trueClassColumn: str = None
    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {}


@dataclass(repr=False)
class DataFramesPanel(Panel):
    # dataFrameKey: str = None
    # filters: dict = None  # {'$ref': '#/definitions/RootFilter'}
    # groupKeys: list = None
    # previewColumns: list = None
    # previews: list = None
    # showPreview: bool = None
    # sort: str = None
    # tableSettings: dict = None  # {'$ref': '#/definitions/Config'}
    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {}


@dataclass(repr=False)
class MediaBrowserPanel(Panel):
    # molecule also falls under here?
    # actualSize: bool = None
    # boundingBoxConfig: dict = None  # {'$ref': '#/definitions/AllBoundingBoxControls'}
    # chartTitle: str = None
    columns: int = (None,)  # columnCount: float = None
    # fitToDimension: bool = None
    # gallerySettings: dict = None  # {'additionalProperties': False, 'properties': {'axis': {'$ref': '#/definitions/Axis'}}, 'required': ['axis'], 'type': 'object'}
    # gridSettings: dict = None  # {'additionalProperties': False, 'properties': {'xAxis': {'$ref': '#/definitions/Axis'}, 'yAxis': {'$ref': '#/definitions/Axis'}}, 'required': ['xAxis', 'yAxis'], 'type': 'object'}
    # maxGalleryItems: float = None
    # maxYAxisCount: float = None
    # mediaIndex: float = None
    media_keys: list = None  # mediaKeys: list = None
    # mode: dict = None  # {'$ref': '#/definitions/PanelModes'}
    # moleculeConfig: dict = None  # {'$ref': '#/definitions/MoleculeConfig'}
    # page: dict = None  # {'additionalProperties': False, 'properties': {'start': {'type': 'number'}}, 'type': 'object'}
    # pixelated: bool = None
    # segmentationMaskConfig: dict = None  # {'$ref': '#/definitions/AllMaskControls'}
    # selection: dict = None  # {'additionalProperties': False, 'properties': {'xAxis': {'items': {'type': 'number'}, 'maxItems': 2, 'minItems': 2, 'type': 'array'}, 'yAxis': {'items': {'type': 'number'}, 'maxItems': 2, 'minItems': 2, 'type': 'array'}}, 'type': 'object'}
    # snapToExistingStep: bool = None
    # stepIndex: float = None
    # stepStrideLength: float = None
    # tileLayout: dict = None  # {'additionalProperties': {'additionalProperties': False, 'properties': {'maskOptions': {'items': {'$ref': '#/definitions/MaskOptions'}, 'type': 'array'}, 'type': {'$ref': '#/definitions/LayoutType'}}, 'required': ['type', 'maskOptions'], 'type': 'object'}, 'type': 'object'}
    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {"columns": "columnCount", "media_keys": "mediaKeys"}


@dataclass(repr=False)
class MoleculePanel(MediaBrowserPanel):
    # representation: dict = None  # {'$ref': '#/definitions/RepresentationType'}
    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {}


@dataclass(repr=False)
class MultiRunTablePanel(Panel):
    # cellColumnKey: dict = None  # {'anyOf': [{'items': {'type': ['string', 'number', 'boolean']}, 'type': 'array'}, {'type': 'string'}, {'type': 'number'}, {'type': 'boolean'}]}
    # pageSize: float = None
    # rowColumnKeys: list = None
    # tableKey: str = None
    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {}


@dataclass(repr=False)
class ParameterImportancePanel(Panel):
    # parameterConf: dict = None
    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {}


@dataclass(repr=False)
class RunComparerPanel(Panel):
    # collapsedTree: dict = None  # {'$ref': '#/definitions/CollapsedTree'}
    diff_only: bool = None  # diffOnly: bool = None

    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {"diff_only": "diffOnly"}


@dataclass(repr=False)
class ScalarChartPanel(Panel):
    aggregate: bool = None  # aggregate: bool = None
    # aggregateMetrics: bool = None
    title: str = None  # chartTitle: str = None
    # expressions: list = None
    # fontSize: dict = None  # {'$ref': '#/definitions/PlotFontSizeOrAuto'}
    # groupAgg: dict = None  # {'$ref': '#/definitions/ChartAggOption'}
    # groupArea: dict = None  # {'$ref': '#/definitions/ChartAreaOption'}
    # groupBy: str = None
    # groupRunsLimit: float = None
    # legendFields: list = None
    # legendTemplate: str = None
    metrics: list = None  # metrics: list = None
    # showLegend: bool = None

    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {
        "aggregate": "aggregate",
        "title": "chartTitle",
        "metrics": "metrics",
    }


@dataclass(repr=False)
class ScatterPlotPanel(Panel):
    title: str = None  # chartTitle: str = None
    color: str = None  # color: str = None
    # customGradient: list = None
    # fontSize: dict = None  # {'$ref': '#/definitions/PlotFontSizeOrAuto'}
    # legendFields: list = None
    # maxColor: str = None
    # minColor: str = None
    # showAvgYAxisLine: bool = None
    # showMaxYAxisLine: bool = None
    # showMinYAxisLine: bool = None
    x: str = None  # xAxis: str = None
    range_x: list = None
    log_x: bool = None
    # xAxisLogScale: bool = None
    # xAxisMax: float = None
    # xAxisMin: float = None
    y: str = None  # yAxis: str = None
    range_y: list = None
    log_y: bool = None
    # yAxisLineSmoothingWeight: float = None
    # yAxisLogScale: bool = None
    # yAxisMax: float = None
    # yAxisMin: float = None
    z: str = None
    range_z: list = None
    log_z: bool = None
    # zAxis: str = None
    # zAxisLogScale: bool = None
    # zAxisMax: float = None
    # zAxisMin: float = None
    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {
        "title": "chartTitle",
        "color": "color",
        "x": "xAxis",
        "range_x": ["xAxisMin", "xAxisMax"],
        "log_x": "xAxisLogScale",
        "y": "xAxis",
        "range_y": ["yAxisMin", "yAxisMax"],
        "log_y": "yAxisLogScale",
        "z": "xAxis",
        "range_z": ["zAxisMin", "zAxisMax"],
        "log_z": "zAxisLogScale",
    }


@dataclass(repr=False)
class VegaPanel(Panel):
    # customPanelDef: dict = None  # {'$ref': '#/definitions/VegaPanelDef'}
    # fieldSettings: dict = (
    #     None  # {'additionalProperties': {'type': 'string'}, 'type': 'object'}
    # )
    # historyFieldSettings: dict = (
    #     None  # {'additionalProperties': {'type': 'string'}, 'type': 'object'}
    # )
    # panelDefId: str = None
    # runFieldListSettings: dict = (
    #     None  # {'additionalProperties': {'type': 'string'}, 'type': 'object'}
    # )
    # runFieldSettings: dict = (
    #     None  # {'additionalProperties': {'type': 'string'}, 'type': 'object'}
    # )
    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {}


@dataclass(repr=False)
class Vega2Panel(Panel):
    # transform: dict = None
    # userQuery: dict = None
    # fieldSettings: dict = None
    # stringSettings: dict = None
    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {}


@dataclass(repr=False)
class Vega3Panel(Panel):
    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {}


@dataclass(repr=False)
class MarkdownPanel(Panel):
    value: str = None  # value: str = None

    def __post_init__(self):
        super().__init__()

    _attr_json_mapping = {"value": "value"}


panel_mapping = {
    "Bar Chart": BarPlotPanel,
    "Code Comparer": CodeComparerPanel,
    "Confusion Matrix": ConfusionMatrixPanel,
    "Data Frame Table": DataFramesPanel,
    "Markdown Panel": MarkdownPanel,
    "Media Browser": MediaBrowserPanel,
    "Multi Run Table": MultiRunTablePanel,
    "Parallel Coordinates Plot": ParallelCoordinatesPanel,
    "Parameter Importance": ParameterImportancePanel,
    "Run Comparer": RunComparerPanel,
    "Run History Line Plot": LinePlotPanel,
    "Scalar Chart": ScalarChartPanel,
    "Scatter Plot": ScatterPlotPanel,
    "Vega": VegaPanel,
    "Vega2": Vega2Panel,
    "Vega3": Vega3Panel,
    "Weave": WeavePanel,
}
