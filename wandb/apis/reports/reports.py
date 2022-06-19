from abc import abstractmethod
from dataclasses import dataclass
import json
import re
from typing import List as LList, Union
import urllib.parse

import wandb
from wandb.apis.public import Runs
from wandb.sdk.lib import ipython
from wandb.sdk.wandb_require_helpers import RequiresReportEditingMixin

from .mutations import CREATE_PROJECT, UPSERT_VIEW
from .util import (
    _generate_default_panel_layout,
    Attr,
    BaseMeta,
    BlockOrPanelBase,
    find,
    fix_collisions,
    generate_name,
    JSONAttr,
    nested_set,
    ReportBase,
    RequiredAttr,
    RequiredJSONAttr,
    RunSetBase,
    ShortReprMixin,
    SubclassOnlyABC,
    tuple_factory,
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

api = wandb.Api()


def blocks_get(attr, report):
    blocks = []
    for block in report.spec["blocks"]:
        cls = block_mapping[block["type"]]  # noqa: N806
        blocks.append(cls.from_json(spec=block))
    return blocks[1:-1]  # ignore the padding P blocks


def blocks_set(attr, report, new_blocks):
    # Add padding P blocks
    report.spec["blocks"] = [P().spec] + [b.spec for b in new_blocks] + [P().spec]


@dataclass(repr=False)
class Report(ReportBase, ShortReprMixin, RequiresReportEditingMixin):
    project: str = RequiredJSONAttr("project.name", base_path="_viewspec")
    entity: str = JSONAttr(
        "project.entityName", base_path="_viewspec", default=api.default_entity
    )
    title: str = JSONAttr(
        "displayName", base_path="_viewspec", default="Untitled Report"
    )
    description: str = JSONAttr("description", base_path="_viewspec", default="")
    width: str = JSONAttr("width", default="readable")
    blocks: list = Attr(default_factory=list, fget=blocks_get, fset=blocks_set)

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


class Dispatcher(SubclassOnlyABC):
    @classmethod
    @abstractmethod
    def from_json(cls, spec):
        pass


@dataclass(repr=False)
class Block(BlockOrPanelBase, Dispatcher, ShortReprMixin):
    @property
    @abstractmethod
    def spec(self):
        pass


def panels_get(attr, pg):
    panels = []
    for pspec in pg.spec["metadata"]["panelBankSectionConfig"]["panels"]:
        cls = panel_mapping[pspec["viewType"]]
        panels.append(cls.from_json(pspec))
    return panels


def panels_set(attr, pg, new_panels):
    panels = [p.spec for p in fix_collisions(new_panels)]
    pg.spec["metadata"]["panelBankSectionConfig"]["panels"] = panels


def runsets_get(attr, pg):
    return [RunSet.from_json(spec) for spec in pg.spec["metadata"]["runSets"]]


def runsets_set(attr, pg, new_runsets):
    runsets = [rs.spec for rs in new_runsets]
    pg.spec["metadata"]["runSets"] = runsets


@dataclass(repr=False)
class PanelGrid(Block):
    panels: list = Attr(default_factory=list, fget=panels_get, fset=panels_set)
    runsets: list = Attr(default_factory=list, fget=runsets_get, fset=runsets_set)

    @property
    def spec(self) -> dict:
        return self._spec


def rs_filter_get(attr, runset):
    return runset.query_generator.filter_to_mongo(runset.spec["filters"])


def rs_filter_set(attr, runset, value):
    runset.spec["filters"] = runset.query_generator.mongo_to_filter(value)


def rs_groupby_get(attr, runset):
    cols = [
        runset.query_generator.key_to_server_path(k) for k in runset.spec["grouping"]
    ]
    return [runset.pm_query_generator.back_to_front(col) for col in cols]


def rs_groupby_set(attr, runset, value):
    cols = [runset.pm_query_generator.front_to_back(v) for v in value]
    runset.spec["grouping"] = [
        runset.query_generator.server_path_to_key(k) for k in cols
    ]


def rs_order_get(attr, runset):
    cols = runset.query_generator.keys_to_order(runset.spec["sort"])
    return [col[0] + runset.pm_query_generator.back_to_front(col[1:]) for col in cols]


def rs_order_set(attr, runset, value):
    cols = [v[0] + runset.pm_query_generator.front_to_back(v[1:]) for v in value]
    return runset.query_generator.order_to_keys(cols)


@dataclass(repr=False)
class RunSet(RunSetBase, ShortReprMixin):
    entity: str = JSONAttr("project.entityName")
    project: str = JSONAttr("project.name")
    name: str = JSONAttr("name")
    query: str = JSONAttr("search.query")
    filters: dict = JSONAttr("filters", fget=rs_filter_get, fset=rs_filter_set)
    groupby: list = JSONAttr(
        "grouping", fget=rs_groupby_get, fset=rs_groupby_set, default_factory=list
    )
    order: list = JSONAttr(
        "sort", fget=rs_order_get, fset=rs_order_set, default_factory=list
    )

    @property
    def spec(self) -> dict:
        return self._spec

    def set_filters_with_python_expr(self, expr: str) -> None:
        self.filters = self.pm_query_generator.python_to_mongo(expr)

    @property
    def runs(self) -> Runs:
        return Runs(api.client, self.entity, self.project)

    @property
    def _runs_config(self) -> dict:
        return {k: v for run in self.runs for k, v in run.config.items()}


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
    def from_panel_agg(cls, runset: RunSet, panel: "Panel", metric: str) -> "LineKey":
        key = f"{runset.id}-config:group:{panel.groupby}:null:{metric}"
        return cls(key)

    @classmethod
    def from_runset_agg(cls, runset: RunSet, metric: str) -> "LineKey":
        groupby = runset.groupby
        if runset.groupby is None:
            groupby = "null"

        key = f"{runset.id}-run:group:{groupby}:{metric}"
        return cls(key)


@dataclass
class RGBA(metaclass=BaseMeta):
    r: int = RequiredAttr(validators=[Between(0, 255)])
    g: int = RequiredAttr(validators=[Between(0, 255)])
    b: int = RequiredAttr(validators=[Between(0, 255)])
    a: Union[int, float] = Attr(validators=[Between(0, 1)])

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
class Panel(BlockOrPanelBase, ShortReprMixin):
    layout: dict = JSONAttr("layout", default_factory=_generate_default_panel_layout)

    @property
    def spec(self):
        return self._spec

    @property
    def config(self):
        return self._spec["config"]

    def __post_init__(self):
        self._spec["viewType"] = self.view_type


def line_override_get(attr, panel):
    titles = find(panel.spec, attr.path)
    return {LineKey(k): v for k, v in titles.items()} if titles is not None else None


def line_override_set(attr, panel, value):
    titles = (
        {linekey.key: v for linekey, v in value.items()} if value is not None else None
    )
    nested_set(panel.spec, attr.path, titles)


def line_color_override_get(attr, panel):
    colors = find(panel.spec, attr.path)
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
    nested_set(panel.spec, attr.path, colors)


@dataclass(repr=False)
class LinePlot(Panel):
    title: str = JSONAttr("config.chartTitle")
    x: str = JSONAttr("config.xAxis")
    y: list = JSONAttr("config.metrics")
    range_x: Union[list, tuple] = JSONAttr(
        ["config.xAxisMin", "config.xAxisMax"],
        default_factory=tuple_factory(size=2),
        validators=[Length(2), TypeValidator((int, float), how="keys")],
    )
    range_y: Union[list, tuple] = JSONAttr(
        ["config.yAxisMin", "config.yAxisMax"],
        default_factory=tuple_factory(size=2),
        validators=[Length(2), TypeValidator((int, float), how="keys")],
    )
    log_x: bool = JSONAttr("config.xLogScale")
    log_y: bool = JSONAttr("config.yLogScale")
    title_x: str = JSONAttr("config.xAxisTitle")
    title_y: str = JSONAttr("config.yAxisTitle")
    ignore_outliers: bool = JSONAttr("config.ignoreOutliers")
    groupby: str = JSONAttr("config.groupBy")
    groupby_aggfunc: str = JSONAttr("config.groupAgg", validators=[OneOf(AGGFUNCS)])
    groupby_rangefunc: str = JSONAttr(
        "config.groupArea", validators=[OneOf(RANGEFUNCS)]
    )
    smoothing_factor: float = JSONAttr("config.smoothingWeight")
    smoothing_type: str = JSONAttr(
        "config.smoothingType", validators=[OneOf(SMOOTHING_TYPES)]
    )
    smoothing_show_original: bool = JSONAttr("config.showOriginalAfterSmoothing")
    max_runs_to_show: int = JSONAttr("config.limit")
    custom_expressions: str = JSONAttr("config.expressions")
    plot_type: str = JSONAttr("config.plotType", validators=[OneOf(LINEPLOT_STYLES)])
    font_size: str = JSONAttr("config.fontSize", validators=[OneOf(FONT_SIZES)])
    legend_position: str = JSONAttr(
        "config.legendPosition", validators=[OneOf(LEGEND_POSITIONS)]
    )
    legend_template: str = JSONAttr("config.legendTemplate")

    # JSONAttr("config.startingXAxis")
    # JSONAttr("config.useLocalSmoothing")
    # JSONAttr("config.useGlobalSmoothingWeight")
    # JSONAttr("config.legendFields")
    aggregate: bool = JSONAttr("config.aggregate")
    # JSONAttr("config.aggregateMetrics")
    # JSONAttr("config.metricRegex")
    # JSONAttr("config.useMetricRegex")
    # JSONAttr("config.yAxisAutoRange")
    # JSONAttr("config.groupRunsLimit")
    xaxis_expression: str = JSONAttr("config.xExpression")
    # JSONAttr("config.colorEachMetricDifferently")
    # JSONAttr("config.showLegend")

    line_titles: dict = JSONAttr(
        "config.overrideSeriesTitles",
        default_factory=dict,
        fget=line_override_get,
        fset=line_override_set,
        validators=[
            TypeValidator(LineKey, how="keys"),
            TypeValidator(str, how="values"),
        ],
    )
    line_marks: dict = JSONAttr(
        "config.overrideMarks",
        default_factory=dict,
        fget=line_override_get,
        fset=line_override_set,
        validators=[TypeValidator(LineKey, how="keys"), OneOf(MARKS, how="values")],
    )
    line_colors: dict = JSONAttr(
        "config.overrideColors",
        default_factory=dict,
        fget=line_color_override_get,
        fset=line_color_override_set,
        validators=[
            TypeValidator(LineKey, how="keys"),
            TypeValidator(RGBA, how="values"),
        ],
    )
    line_widths: dict = JSONAttr(
        "config.overrideLineWidths",
        default_factory=dict,
        fget=line_override_get,
        fset=line_override_set,
        validators=[
            TypeValidator(LineKey, how="keys"),
            TypeValidator((float, int), how="values"),
            Between(0.5, 3.0, how="values"),
        ],
    )

    @property
    def view_type(self) -> str:
        return "Run History Line Plot"

    def __post_init__(self) -> None:
        super().__post_init__()


@dataclass(repr=False)
class ScatterPlot(Panel):
    title: str = JSONAttr("config.chartTitle")
    x: str = JSONAttr("config.xAxis")
    y: str = JSONAttr("config.yAxis")
    z: str = JSONAttr("config.zAxis")
    range_x: Union[list, tuple] = JSONAttr(
        ["config.xAxisMin", "config.xAxisMax"],
        default_factory=tuple_factory(size=2),
        validators=[Length(2), TypeValidator((int, float), how="keys")],
    )
    range_y: Union[list, tuple] = JSONAttr(
        ["config.yAxisMin", "config.yAxisMax"],
        default_factory=tuple_factory(size=2),
        validators=[Length(2), TypeValidator((int, float), how="keys")],
    )
    range_z: Union[list, tuple] = JSONAttr(
        ["config.zAxisMin", "config.zAxisMax"],
        default_factory=tuple_factory(size=2),
        validators=[Length(2), TypeValidator((int, float), how="keys")],
    )
    log_x: bool = JSONAttr("config.xAxisLogScale")
    log_y: bool = JSONAttr("config.yAxisLogScale")
    log_z: bool = JSONAttr("config.zAxisLogScale")
    running_ymin: bool = JSONAttr("config.showMaxYAxisLine")
    running_ymax: bool = JSONAttr("config.showMinYAxisLine")
    running_ymean: bool = JSONAttr("config.showAvgYAxisLine")
    legend_template: str = JSONAttr("config.legendTemplate")
    gradient: dict = JSONAttr(
        "config.customGradient",
        default_factory=dict,
        validators=[TypeValidator(RGBA, how="values")],
    )
    # color: ... = JSONAttr("config.color")
    # range_color: ... = JSONAttr(
    #     ["config.minColor", "config.maxColor"],
    #     (list, tuple),
    #     validators=[Length(2), TypeValidator((int, float), how='keys')],
    # )

    # JSONAttr("config.legendFields")
    font_size: str = JSONAttr("config.fontSize", validators=[OneOf(FONT_SIZES)])
    # JSONAttr("config.yAxisLineSmoothingWeight")

    @property
    def view_type(self) -> str:
        return "Scatter Plot"


@dataclass(repr=False)
class BarPlot(Panel):
    title: str = JSONAttr("config.chartTitle")
    metrics: list = JSONAttr(
        "config.metrics",
        default_factory=list,
        validators=[TypeValidator(str, how="keys")],
    )
    vertical: bool = JSONAttr("config.vertical")
    range_x: Union[list, tuple] = JSONAttr(
        ["config.xAxisMin", "config.xAxisMax"],
        default_factory=tuple_factory(size=2),
        validators=[Length(2), TypeValidator((int, float), how="keys")],
    )
    title_x: str = JSONAttr("config.xAxisTitle")
    title_y: str = JSONAttr("config.yAxisTitle")
    groupby: str = JSONAttr("config.groupBy")
    groupby_aggfunc: str = JSONAttr("config.groupAgg", validators=[OneOf(AGGFUNCS)])
    groupby_rangefunc: str = JSONAttr(
        "config.groupArea", validators=[OneOf(RANGEFUNCS)]
    )
    max_runs_to_show: int = JSONAttr("config.limit")
    max_bars_to_show: int = JSONAttr("config.barLimit")
    custom_expressions: str = JSONAttr("config.expressions")
    legend_template: str = JSONAttr("config.legendTemplate")
    font_size: str = JSONAttr("config.fontSize", validators=[OneOf(FONT_SIZES)])
    # JSONAttr("config.limit")
    # JSONAttr("config.barLimit")
    # JSONAttr("config.aggregate")
    # JSONAttr("config.aggregateMetrics")
    # JSONAttr("config.groupRunsLimit")
    # JSONAttr("config.plotStyle")
    # JSONAttr("config.legendFields")
    # JSONAttr("config.colorEachMetricDifferently")

    line_titles: dict = JSONAttr(
        "config.overrideSeriesTitles",
        default_factory=dict,
        fget=line_override_get,
        fset=line_override_set,
        validators=[
            TypeValidator(LineKey, how="keys"),
            TypeValidator(str, how="values"),
        ],
    )
    line_colors: dict = JSONAttr(
        "config.overrideColors",
        default_factory=dict,
        fget=line_color_override_get,
        fset=line_color_override_set,
        validators=[
            TypeValidator(LineKey, how="keys"),
            TypeValidator(RGBA, how="values"),
        ],
    )

    @property
    def view_type(self) -> str:
        return "Bar Chart"


def scalar_metric_fget(prop, panel):
    result = find(panel.spec, prop.path)
    return result[0] if result else ""


def scalar_metric_fset(prop, panel, value):
    nested_set(panel.spec, prop.path, [value])


@dataclass(repr=False)
class ScalarChart(Panel):
    title: str = JSONAttr("config.chartTitle")
    metric: str = JSONAttr(
        "config.metrics", default="", fget=scalar_metric_fget, fset=scalar_metric_fset
    )
    groupby_aggfunc: str = JSONAttr("config.groupAgg", validators=[OneOf(AGGFUNCS)])
    groupby_rangefunc: str = JSONAttr(
        "config.groupArea", validators=[OneOf(RANGEFUNCS)]
    )
    custom_expressions: str = JSONAttr("config.expressions")
    legend_template: str = JSONAttr("config.legendTemplate")

    # JSONAttr("config.aggregate")
    # JSONAttr("config.aggregateMetrics")
    # JSONAttr("config.groupBy")
    # JSONAttr("config.groupRunsLimit")
    # JSONAttr("config.legendFields")
    # JSONAttr("config.showLegend")
    font_size: str = JSONAttr("config.fontSize", validators=[OneOf(FONT_SIZES)])

    @property
    def view_type(self) -> str:
        return "Scalar Chart"


@dataclass(repr=False)
class CodeComparer(Panel):
    diff: str = JSONAttr("config.diff", validators=[OneOf(CODE_COMPARE_DIFF)])

    @property
    def view_type(self) -> str:
        return "Code Comparer"


@dataclass(repr=False)
class ParallelCoordinatesPlot(Panel):
    columns: list = JSONAttr("config.columns", default_factory=list)
    title: str = JSONAttr("config.chartTitle")

    # JSONAttr("config.dimensions")
    # JSONAttr("config.customGradient")
    # JSONAttr("config.gradientColor")
    # JSONAttr("config.legendFields")
    font_size: str = JSONAttr("config.fontSize", validators=[OneOf(FONT_SIZES)])

    @property
    def view_type(self) -> str:
        return "Parallel Coordinates Plot"


@dataclass(repr=False)
class ParameterImportancePlot(Panel):
    with_respect_to: str = JSONAttr("config.targetKey")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not self.with_respect_to:
            self.with_respect_to = "_timestamp"

    @property
    def view_type(self) -> str:
        return "Parameter Importance"


@dataclass(repr=False)
class RunComparer(Panel):
    diff_only: str = JSONAttr("config.diffOnly", validators=[OneOf(["split", None])])

    @property
    def view_type(self) -> str:
        return "Run Comparer"


@dataclass(repr=False)
class MediaBrowser(Panel):
    num_columns: int = JSONAttr("config.columnCount")
    media_keys: str = JSONAttr("config.media_keys")

    # JSONAttr("config.chartTitle")
    # JSONAttr("config.stepIndex")
    # JSONAttr("config.mediaIndex")
    # JSONAttr("config.actualSize")
    # JSONAttr("config.fitToDimension")
    # JSONAttr("config.pixelated")
    # JSONAttr("config.mode")
    # JSONAttr("config.gallerySettings")
    # JSONAttr("config.gridSettings")
    # JSONAttr("config.selection")
    # JSONAttr("config.page")
    # JSONAttr("config.tileLayout")
    # JSONAttr("config.stepStrideLength")
    # JSONAttr("config.snapToExistingStep")
    # JSONAttr("config.maxGalleryItems")
    # JSONAttr("config.maxYAxisCount")
    # JSONAttr("config.moleculeConfig")
    # JSONAttr("config.segmentationMaskConfig")
    # JSONAttr("config.boundingBoxConfig")

    @property
    def view_type(self) -> str:
        return "Media Browser"


@dataclass(repr=False)
class MarkdownPanel(Panel):
    markdown: str = JSONAttr("config.value")

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


class List(Dispatcher):
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


@dataclass(repr=False)
class CheckedList(Block, List):
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


@dataclass(repr=False)
class OrderedList(Block, List):
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


@dataclass(repr=False)
class UnorderedList(Block, List):
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


class Heading(Dispatcher):
    @classmethod
    def from_json(cls, spec: dict) -> "Union[H1,H2,H3]":
        level = spec["level"]
        text = spec["children"][0]["text"]

        level_mapping = {1: H1, 2: H2, 3: H3}

        if level not in level_mapping:
            raise ValueError(f"`level` must be one of {list(level_mapping.keys())}")

        return level_mapping[level](text)


@dataclass(repr=False)
class H1(Block, Heading):
    text: str = Attr()

    @property
    def spec(self) -> dict:
        return {
            "type": "heading",
            "children": [{"text": self.text}],
            "level": 1,
        }


@dataclass(repr=False)
class H2(Block, Heading):
    text: str = Attr()

    @property
    def spec(self) -> dict:
        return {
            "type": "heading",
            "children": [{"text": self.text}],
            "level": 2,
        }


@dataclass(repr=False)
class H3(Block, Heading):
    text: str = Attr()

    @property
    def spec(self) -> dict:
        return {
            "type": "heading",
            "children": [{"text": self.text}],
            "level": 3,
        }


@dataclass(repr=False)
class P(Block):
    text: str = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "P":
        # Edge case: Inline LaTeX, not Paragraph
        if len(spec["children"]) == 3 and spec["children"][1]["type"] == "latex":
            return LaTeXInline.from_json(spec)

        text = spec["children"][0]["text"]
        return cls(text)

    @property
    def spec(self) -> dict:
        return {
            "type": "paragraph",
            "children": [{"text": self.text}],
        }


@dataclass(repr=False)
class BlockQuote(Block):
    text: str = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "BlockQuote":
        text = spec["children"][0]["text"]
        return cls(text)

    @property
    def spec(self) -> dict:
        return {"type": "block-quote", "children": [{"text": self.text}]}


@dataclass(repr=False)
class CalloutBlock(Block):
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


@dataclass(repr=False)
class CodeBlock(Block):
    code: Union[str, list] = Attr()
    language: str = Attr(default="python")

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


@dataclass(repr=False)
class MarkdownBlock(Block):
    text: Union[str, list] = Attr()

    def __post_init__(self) -> None:
        if isinstance(self.text, list):
            self.text = "\n".join(self.text)

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


@dataclass(repr=False)
class LaTeXInline(Block):
    before: Union[str, list] = Attr()
    latex: Union[str, list] = Attr()
    after: Union[str, list] = Attr()

    def __post_init__(self) -> None:
        if isinstance(self.before, list):
            self.before = "\n".join(self.before)
        if isinstance(self.latex, list):
            self.latex = "\n".join(self.latex)
        if isinstance(self.after, list):
            self.after = "\n".join(self.after)

    @classmethod
    def from_json(cls, spec: dict) -> "LaTeXInline":
        before = spec["children"][0]["text"]
        latex = spec["children"][1]["content"]
        after = spec["children"][2]["text"]
        return cls(before, latex, after)

    @property
    def spec(self) -> dict:
        return {
            "type": "paragraph",
            "children": [
                {"text": self.before},
                {"type": "latex", "children": [{"text": ""}], "content": self.latex},
                {"text": self.after},
            ],
        }


@dataclass(repr=False)
class LaTeXBlock(Block):
    text: Union[str, list] = Attr()

    def __post_init__(self) -> None:
        if isinstance(self.text, list):
            self.text = "\n".join(self.text)

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


@dataclass(repr=False)
class Gallery(Block):
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


@dataclass(repr=False)
class Image(Block):
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


@dataclass(repr=False)
class WeaveBlock(Block):
    spec: dict = Attr()

    @classmethod
    def from_json(cls, spec: dict) -> "WeaveBlock":
        return cls(spec)


@dataclass(repr=False)
class HorizontalRule(Block):
    @classmethod
    def from_json(cls, spec: dict) -> "HorizontalRule":
        return cls()

    @property
    def spec(self):
        return {"type": "horizontal-rule", "children": [{"text": ""}]}


@dataclass(repr=False)
class TableOfContents(Block):
    @classmethod
    def from_json(cls, spec: dict) -> "TableOfContents":
        return cls()

    @property
    def spec(self) -> dict:
        return {"type": "table-of-contents", "children": [{"text": ""}]}


@dataclass(repr=False)
class SoundCloud(Block):
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


@dataclass(repr=False)
class Twitter(Block):
    embed_html: str = Attr()

    def __post_init__(self) -> None:
        # remove script tag
        if self.embed_html:
            pattern = r" <script[\s\S]+?/script>"
            self.embed_html = re.sub(pattern, "\n", self.embed_html)

    @classmethod
    def from_json(cls, spec: dict) -> "Twitter":
        embed_html = spec["html"]
        return cls(embed_html)

    @property
    def spec(self) -> dict:
        return {"type": "twitter", "html": self.embed_html, "children": [{"text": ""}]}


@dataclass(repr=False)
class Spotify(Block):
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


@dataclass(repr=False)
class Video(Block):
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


# Need to add validators after all classes are defined :/

Report.blocks.validators += [TypeValidator(Block, how="keys")]
PanelGrid.panels.validators += [TypeValidator(Panel, how="keys")]
PanelGrid.runsets.validators += [TypeValidator(RunSet, how="keys")]
PanelGrid.runsets.default_factory = lambda: [RunSet()]
