"""JSONSchema for internal types.  Hopefully this is auto-generated one day!"""
import ast
import json
import random
import re
from copy import deepcopy
from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, validator
from pydantic.alias_generators import to_camel


def _generate_name(length: int = 12) -> str:
    """Generate a random name.

    This implementation roughly based the following snippet in core:
    https://github.com/wandb/core/blob/master/lib/js/cg/src/utils/string.ts#L39-L44.
    """

    # Borrowed from numpy: https://github.com/numpy/numpy/blob/v1.23.0/numpy/core/numeric.py#L2069-L2123
    def base_repr(number: int, base: int, padding: int = 0) -> str:
        digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if base > len(digits):
            raise ValueError("Bases greater than 36 not handled in base_repr.")
        elif base < 2:
            raise ValueError("Bases less than 2 not handled in base_repr.")

        num = abs(number)
        res = []
        while num:
            res.append(digits[num % base])
            num //= base
        if padding:
            res.append("0" * padding)
        if number < 0:
            res.append("-")
        return "".join(reversed(res or "0"))

    rand = random.random()
    rand = int(float(str(rand)[2:]))
    rand36 = base_repr(rand, 36)
    return rand36.lower()[:length]


LinePlotStyle = Literal["line", "stacked-area", "pct-area"]
BarPlotStyle = Literal["bar", "boxplot", "violin"]
FontSize = Literal["small", "medium", "large", "auto"]
LegendPosition = Literal["north", "south", "east", "west"]
LegendOrientation = Literal["horizontal", "vertical"]
GroupAgg = Literal["mean", "min", "max", "median", "sum", "samples"]
GroupArea = Literal["minmax", "stddev", "stderr", "none", "samples"]
Mark = Literal["solid", "dashed", "dotted", "dotdash", "dotdotdash"]
Timestep = Literal["seconds", "minutes", "hours", "days"]
SmoothingType = Literal["exponential", "gaussian", "average", "none"]
CodeCompareDiff = Literal["split", "unified"]
Range = tuple[Optional[float], Optional[float]]
Language = Literal["javascript", "python", "css", "json", "html", "markdown", "yaml"]
Ops = Literal["OR", "AND", "=", "!=", "<=", ">=", "IN", "NIN", "=="]
TextLikeInternal = Union["InlineLatex", "InlineLink", "Paragraph", "Text"]
GalleryLink = Union["GalleryLinkReport", "GalleryLinkURL"]
ReportWidth = Literal["readable", "fixed", "fluid"]


class TextLikeMixin:
    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        data["children"] = [c.model_dump() for c in self.children]
        return data

    @classmethod
    def model_validate(cls, data):
        d = deepcopy(data)
        children = []
        for c in d.get("children"):
            if (_type := c.get("type")) == "link":
                child = InlineLink.model_validate(c)
            elif _type == "latex":
                child = InlineLatex.model_validate(c)
            elif _type == "paragraph":
                child = Paragraph.model_validate(c)
            else:
                child = Text.model_validate(c)
            children.append(child)

        d["children"] = children
        obj = cls(**d)
        return obj


class Sentinel(BaseModel):
    ...


class ReportEntity(Sentinel):
    ...


class ReportProject(Sentinel):
    ...


class ReportAPIBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        # loc_by_alias=False,
        use_enum_values=True,
        validate_assignment=True,
        populate_by_name=True,
        arbitrary_types_allowed=True,
        # extra="forbid",
    )


class UnknownBlock(ReportAPIBaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        # loc_by_alias=False,
        use_enum_values=True,
        validate_assignment=True,
        populate_by_name=True,
        arbitrary_types_allowed=True,
        extra="allow",
    )


class InlineModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        # loc_by_alias=False,
        use_enum_values=True,
        validate_assignment=True,
        populate_by_name=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )


class Ref(ReportAPIBaseModel):
    type: str = ""
    view_id: str = ""
    id: str = ""


class Text(ReportAPIBaseModel):
    text: str = ""
    inline_code: Optional[bool] = None

    inline_comments: Optional[list["InlineComment"]] = None

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        if (comments := self.inline_comments) is None:
            comments = []
        for comment in comments:
            ref_id = comment.ref_id
            data[f"inlineComment_{ref_id}"] = comment.model_dump()
        data.pop("inline_comments", None)
        return data

    @classmethod
    def model_validate(cls, data):
        d = deepcopy(data)
        obj = cls(**d)

        inline_comments = []
        for k, v in d.items():
            if k.startswith("inlineComment"):
                comment = InlineComment.model_validate(v)
                inline_comments.append(comment)
        obj.inline_comments = inline_comments
        return obj


class Project(ReportAPIBaseModel):
    name: Optional[str] = None
    # name: str = ""
    entity_name: str = ""


class PanelBankConfigSettings(ReportAPIBaseModel):
    auto_organize_prefix: int = 2
    show_empty_sections: bool = False
    sort_alphabetically: bool = False


class FlowConfig(ReportAPIBaseModel):
    snap_to_columns: bool = True
    columns_per_page: int = 3
    rows_per_page: int = 2
    gutter_width: int = 16
    box_width: int = 460
    box_height: int = 300


class LocalPanelSettings(ReportAPIBaseModel):
    x_axis: str = "_step"
    smoothing_weight: int = 0
    smoothing_type: str = "exponential"
    ignore_outliers: bool = False
    x_axis_active: bool = False
    smoothing_active: bool = False
    # ref: dict = Field(default_factory=dict)
    ref: Optional[Ref] = None


class PanelBankConfigSectionsItem(ReportAPIBaseModel):
    name: str = "Hidden Panels"
    is_open: bool = False
    type: str = "flow"
    flow_config: FlowConfig = Field(default_factory=FlowConfig)
    sorted: int = 0
    local_panel_settings: LocalPanelSettings = Field(default_factory=LocalPanelSettings)
    panels: list = Field(default_factory=list)
    # local_panel_settings_ref: dict = Field(default_factory=dict)
    # panel_refs: list = Field(default_factory=list)
    # ref: dict = Field(default_factory=dict)
    ref: Optional[Ref] = None


class PanelBankConfig(ReportAPIBaseModel):
    state: int = 0
    settings: PanelBankConfigSettings = Field(default_factory=PanelBankConfigSettings)
    sections: list[PanelBankConfigSectionsItem] = Field(
        default_factory=lambda: [PanelBankConfigSectionsItem()]
    )


class PanelBankSectionConfig(ReportAPIBaseModel):
    name: Literal["Report Panels"] = "Report Panels"
    is_open: bool = False
    panels: list["PanelTypes"] = Field(default_factory=list)
    type: Literal["grid"] = "grid"
    flow_config: FlowConfig = Field(default_factory=FlowConfig)
    sorted: int = 0
    local_panel_settings: LocalPanelSettings = Field(default_factory=LocalPanelSettings)


class PanelGridCustomRunColors(ReportAPIBaseModel):
    ref: Ref


class PanelGridMetadataPanels(ReportAPIBaseModel):
    views: dict = Field(
        default_factory=lambda: {"0": {"name": "Panels", "defaults": [], "config": []}}
    )
    tabs: list = Field(default_factory=lambda: ["0"])
    # ref: Ref = Field(default_factory=Ref)
    ref: Optional[Ref] = None


class PanelGridMetadata(ReportAPIBaseModel):
    open_viz: bool = True
    open_run_set: Optional[int] = 0  # none is closed
    name: Literal["unused-name"] = "unused-name"
    run_sets: list["Runset"] = Field(default_factory=lambda: [Runset()])
    panels: PanelGridMetadataPanels = Field(default_factory=PanelGridMetadataPanels)
    panel_bank_config: PanelBankConfig = Field(default_factory=PanelBankConfig)
    panel_bank_section_config: PanelBankSectionConfig = Field(
        default_factory=PanelBankSectionConfig
    )
    custom_run_colors: dict = Field(default_factory=dict)
    # custom_run_colors: PanelGridCustomRunColors = Field(
    #     default_factory=PanelGridCustomRunColors
    # )


class Block(ReportAPIBaseModel):
    ...


class PanelGrid(Block):
    type: Literal["panel-grid"] = "panel-grid"
    children: list[Text] = Field(default_factory=lambda: [Text()])
    metadata: PanelGridMetadata = Field(default_factory=PanelGridMetadata)


class RunsetSearch(ReportAPIBaseModel):
    query: str = ""


class RunFeed(ReportAPIBaseModel):
    version: int = 2
    column_visible: dict[str, bool] = Field(default_factory=lambda: {"run:name": False})
    column_pinned: dict[str, bool] = Field(default_factory=dict)
    column_widths: dict[str, int] = Field(default_factory=dict)
    column_order: list[str] = Field(default_factory=list)
    page_size: int = 10
    only_show_selected: bool = False


class Key(ReportAPIBaseModel):
    section: str = "summary"
    name: str = ""


class Filters(ReportAPIBaseModel):
    op: Ops = "OR"
    key: Optional[Key] = None
    filters: Optional[list["Filters"]] = None
    ref: Optional[Ref] = None
    value: Optional[Any] = None
    disabled: Optional[bool] = None


class SortKeyKey(ReportAPIBaseModel):
    section: str = "run"
    name: str = "createdAt"


class SortKey(ReportAPIBaseModel):
    key: SortKeyKey = Field(default_factory=SortKeyKey)
    ascending: bool = False


class Sort(ReportAPIBaseModel):
    keys: list[SortKey] = Field(default_factory=lambda: [SortKey()])
    # ref: Ref = Field(default_factory=Ref)
    ref: Optional[Ref] = None


class Runset(ReportAPIBaseModel):
    id: str = _generate_name()
    run_feed: RunFeed = Field(default_factory=RunFeed)
    enabled: bool = True
    project: Optional[Project] = None
    name: str = "Run set"
    search: RunsetSearch = Field(default_factory=RunsetSearch)
    filters: Filters = Field(
        default_factory=lambda: Filters(filters=[Filters(op="AND")])
    )
    grouping: list[Key] = Field(default_factory=list)
    sort: Sort = Field(default_factory=Sort)
    # selections: dict = Field(default_factory=dict)
    selections: dict = Field(
        default_factory=lambda: {"root": 1, "bounds": [], "tree": []}
    )
    expanded_row_addresses: list = Field(default_factory=list)
    # ref: Ref = Field(default_factory=Ref)
    ref: Optional[Ref] = None


class CodeLine(ReportAPIBaseModel):
    type: Literal["code-line"] = "code-line"
    children: list[TextLikeInternal] = Field(default_factory=lambda: [Text()])
    language: Optional[Language] = "python"


class Heading(TextLikeMixin, Block):
    type: Literal["heading"] = "heading"
    children: list[TextLikeInternal] = Field(default_factory=lambda: [Text()])
    collapsed_children: Optional[list["BlockTypes"]] = None
    level: int = 1


class InlineLatex(InlineModel):
    type: Literal["latex"] = "latex"
    children: list[Text] = Field(default_factory=lambda: [Text()])
    content: str = ""


class InlineLink(TextLikeMixin, InlineModel):
    type: Literal["link"] = "link"
    url: str = "https://"
    children: list[Text] = Field(default_factory=lambda: [Text()])


class Paragraph(TextLikeMixin, Block):
    type: Literal["paragraph"] = "paragraph"
    children: list[TextLikeInternal] = Field(default_factory=lambda: [Text()])

    model_config = ConfigDict(
        alias_generator=to_camel,
        # loc_by_alias=False,
        use_enum_values=True,
        validate_assignment=True,
        populate_by_name=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )

    @validator("children", pre=True, each_item=True)
    def parse_children(cls, v):  # noqa: N805
        if isinstance(v, BaseModel):
            v = v.model_dump()
        if isinstance(v, dict):
            if v.get("type") == "latex":
                return InlineLatex(**v)
            elif v.get("type") == "link":
                return InlineLink(**v)
        return Text(**v)


class BlockQuote(Block):
    type: Literal["block-quote"] = "block-quote"
    children: list[TextLikeInternal] = Field(default_factory=lambda: [Text()])


class CodeBlock(Block):
    type: Literal["code-block"] = "code-block"
    children: list[CodeLine] = Field(default_factory=lambda: [CodeLine()])
    language: Optional[Language] = "python"


class MarkdownBlock(Block):
    type: Literal["markdown-block"] = "markdown-block"
    children: list[Text] = Field(default_factory=lambda: [Text()])
    content: str = ""


class LatexBlock(Block):
    type: Literal["latex"] = "latex"
    children: list[Text] = Field(default_factory=lambda: [Text()])
    content: str = ""
    block: bool = True


class Image(Block):
    type: Literal["image"] = "image"
    children: list[TextLikeInternal] = Field(default_factory=lambda: [Text()])
    url: str
    has_caption: bool


class ListItem(ReportAPIBaseModel):
    type: Literal["list-item"] = "list-item"
    children: list[TextLikeInternal]
    ordered: Optional[bool] = None
    checked: Optional[bool] = None


class List(Block):
    type: Literal["list"] = "list"
    children: list[ListItem] = Field(default_factory=lambda: [ListItem()])
    ordered: Optional[bool] = None


class CalloutLine(ReportAPIBaseModel):
    type: Literal["callout-line"] = "callout-line"
    children: list[TextLikeInternal] = Field(default_factory=lambda: [Text()])


class CalloutBlock(Block):
    type: Literal["callout-block"] = "callout-block"
    children: list[CalloutLine] = Field(default_factory=lambda: list)


class HorizontalRule(Block):
    type: Literal["horizontal-rule"] = "horizontal-rule"
    children: list[Text] = Field(default_factory=lambda: [Text()])


class Video(Block):
    type: Literal["video"] = "video"
    url: str
    children: list[Text] = Field(default_factory=lambda: [Text()])


class Spotify(Block):
    type: Literal["spotify"] = "spotify"
    spotify_type: Literal["track"] = "track"
    spotify_id: str = Field(..., alias="spotifyID")
    children: list[Text] = Field(default_factory=lambda: [Text()])


class SoundCloud(Block):
    type: Literal["soundcloud"] = "soundcloud"
    html: str
    children: list[Text] = Field(default_factory=lambda: [Text()])


class GalleryLinkReport(ReportAPIBaseModel):
    type: Literal["report"] = "report"
    id: str = ""


class GalleryLinkURL(ReportAPIBaseModel):
    type: Literal["url"] = "url"
    url: str = ""
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = Field(..., alias="imageURL")


class Gallery(Block):
    type: Literal["gallery"] = "gallery"
    children: list[Text] = Field(default_factory=lambda: [Text()])
    links: Optional[list[GalleryLink]] = None
    ids: Optional[list[str]] = None


class TableOfContents(ReportAPIBaseModel):
    type: Literal["table-of-contents"] = "table-of-contents"
    children: list[Text] = Field(default_factory=lambda: [Text()])


class Twitter(ReportAPIBaseModel):
    type: Literal["twitter"] = "twitter"
    children: list[Text] = Field(default_factory=lambda: [Text()])
    html: str


class WeaveBlock(ReportAPIBaseModel):
    type: Literal["weave-panel"] = "weave-panel"
    children: list[Text] = Field(default_factory=lambda: [Text()])
    config: dict = Field(default_factory=dict)


class InlineComment(ReportAPIBaseModel):
    ref_id: str = Field(..., alias="refID")
    thread_id: str = Field(..., alias="threadID")
    comment_id: str = Field(..., alias="commentID")


class Spec(ReportAPIBaseModel):
    version: int = 5
    panel_settings: dict = Field(default_factory=dict)
    blocks: list["BlockTypes"] = Field(default_factory=list)
    width: str = "readable"
    authors: list = Field(default_factory=list)
    discussion_threads: list = Field(default_factory=list)
    ref: dict = Field(default_factory=dict)


class ReportViewspec(ReportAPIBaseModel):
    id: str = ""
    name: str = ""
    display_name: str = ""
    description: str = ""
    project: Project = Field(default_factory=Project)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    spec: Spec = Field(default_factory=Spec)

    @validator("spec", pre=True)
    def parse_json(cls, v):  # noqa: N805
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                raise ValueError("invalid json")
        return v


class Layout(ReportAPIBaseModel):
    x: int = 0
    y: int = 0
    w: int = 8
    h: int = 6


class Panel(ReportAPIBaseModel):
    id: str = Field("", alias="__id__")
    layout: Layout = Field(default_factory=Layout)
    ref: Optional[Ref] = None


class MediaBrowserConfig(ReportAPIBaseModel):
    column_count: Optional[int] = None
    media_keys: list[str] = Field(default_factory=list)


class MediaBrowser(Panel):
    view_type: Literal["Media Browser"] = "Media Browser"
    config: MediaBrowserConfig = Field(default_factory=MediaBrowserConfig)


class MarkdownPanelConfig(ReportAPIBaseModel):
    value: str


class MarkdownPanel(Panel):
    view_type: Literal["Markdown Panel"] = "Markdown Panel"
    config: MarkdownPanelConfig


class LinePlotConfig(ReportAPIBaseModel):
    chart_title: Optional[str] = None
    x_axis: Optional[str] = None
    metrics: list[str] = Field(default_factory=list)
    x_axis_min: Optional[float] = None
    x_axis_max: Optional[float] = None
    y_axis_min: Optional[float] = None
    y_axis_max: Optional[float] = None
    x_log_scale: Optional[bool] = None
    y_log_scale: Optional[bool] = None
    x_axis_title: Optional[str] = None
    y_axis_title: Optional[str] = None
    ignore_outliers: Optional[bool] = None
    group_by: Optional[str] = None
    group_agg: Optional[GroupAgg] = None
    group_area: Optional[GroupArea] = None
    smoothing_weight: Optional[float] = None
    smoothing_type: Optional[SmoothingType] = None
    show_original_after_smoothing: Optional[bool] = None
    limit: Optional[int] = None
    expressions: Optional[list[str]] = None
    plot_type: Optional[LinePlotStyle] = None
    font_size: Optional[FontSize] = None
    legend_position: Optional[LegendPosition] = None
    legend_template: Optional[str] = None
    aggregate: Optional[bool] = None
    x_expression: Optional[str] = None

    override_line_widths: Optional[dict] = None
    override_colors: Optional[dict] = None
    override_series_titles: Optional[dict] = None
    legend_fields: Optional[list] = None

    # there are more here...


class LinePlot(Panel):
    view_type: Literal["Run History Line Plot"] = "Run History Line Plot"
    config: LinePlotConfig = Field(default_factory=LinePlotConfig)


class GradientPoint(ReportAPIBaseModel):
    color: str
    offset: float = Field(0, ge=0, le=100)

    @validator("color")
    def validate_color(cls, v):  # noqa: N805
        if not is_valid_color(v):
            raise ValueError("invalid color, value should be hex, rgb, or rgba")
        return v


class ScatterPlotConfig(ReportAPIBaseModel):
    chart_title: Optional[str] = None
    x_axis: Optional[str] = None
    y_axis: Optional[str] = None
    z_axis: Optional[str] = None
    x_axis_min: Optional[float] = None
    x_axis_max: Optional[float] = None
    y_axis_min: Optional[float] = None
    y_axis_max: Optional[float] = None
    z_axis_min: Optional[float] = None
    z_axis_max: Optional[float] = None
    x_axis_log_scale: Optional[bool] = None
    y_axis_log_scale: Optional[bool] = None
    z_axis_log_scale: Optional[bool] = None
    show_min_y_axis_line: Optional[bool] = None
    show_max_y_axis_line: Optional[bool] = None
    show_avg_y_axis_line: Optional[bool] = None
    legend_template: Optional[str] = None
    custom_gradient: Optional[list[GradientPoint]] = None
    font_size: Optional[FontSize] = None
    show_linear_regression: Optional[bool] = None


class ScatterPlot(Panel):
    view_type: Literal["Scatter Plot"] = "Scatter Plot"
    config: ScatterPlotConfig = Field(default_factory=ScatterPlotConfig)


class BarPlotConfig(ReportAPIBaseModel):
    chart_title: Optional[str] = None
    metric: list[str] = Field(default_factory=list)
    vertical: bool = False
    x_axis_min: Optional[float] = None
    x_axis_max: Optional[float] = None
    x_axis_title: Optional[str] = None
    y_axis_title: Optional[str] = None
    group_by: Optional[str] = None
    group_agg: Optional[GroupAgg] = None
    group_area: Optional[GroupArea] = None
    limit: Optional[int] = None
    bar_limit: Optional[int] = None
    expressions: Optional[list[str]] = None
    legend_template: Optional[str] = None
    font_size: Optional[FontSize] = None
    override_series_titles: Optional[dict] = None
    override_colors: Optional[dict] = None


class BarPlot(Panel):
    view_type: Literal["Bar Chart"] = "Bar Chart"
    config: BarPlotConfig = Field(default_factory=BarPlotConfig)


class ScalarChartConfig(ReportAPIBaseModel):
    chart_title: Optional[str] = None
    metrics: list[str] = Field(default_factory=list)
    group_agg: Optional[GroupAgg] = None
    group_area: Optional[GroupArea] = None
    expressions: Optional[list[str]] = None
    legend_template: Optional[str] = None
    font_size: Optional[FontSize] = None


class ScalarChart(Panel):
    view_type: Literal["Scalar Chart"] = "Scalar Chart"
    config: ScalarChartConfig = Field(default_factory=ScalarChartConfig)


class CodeComparerConfig(ReportAPIBaseModel):
    diff: CodeCompareDiff = "split"


class CodeComparer(Panel):
    view_type: Literal["Code Comparer"] = "Code Comparer"
    config: CodeComparerConfig = Field(default_factory=CodeComparerConfig)


class Column(ReportAPIBaseModel):
    accessor: str
    display_name: Optional[str] = None
    inverted: Optional[bool] = None
    log: Optional[bool] = None
    ref: Optional[Ref] = None


class ParallelCoordinatesPlotConfig(ReportAPIBaseModel):
    chart_title: Optional[str] = None
    columns: list[Column] = Field(default_factory=list)
    custom_gradient: Optional[list[GradientPoint]] = None
    font_size: Optional[FontSize] = None


class ParallelCoordinatesPlot(Panel):
    view_type: Literal["Parallel Coordinates Plot"] = "Parallel Coordinates Plot"
    config: ParallelCoordinatesPlotConfig = Field(
        default_factory=ParallelCoordinatesPlotConfig
    )


class ParameterConf(ReportAPIBaseModel):
    version: int = 2
    column_visible: dict = Field(default_factory=dict)


class ParameterImportancePlotConfig(ReportAPIBaseModel):
    target_key: str
    # parameter_conf: ParameterConf = Field(default_factory=ParameterConf)
    columns_pinned: dict = Field(default_factory=dict)
    column_widths: dict = Field(default_factory=dict)
    column_order: list[str] = Field(default_factory=list)
    page_size: int = 10
    only_show_selected: bool = False


class ParameterImportancePlot(Panel):
    view_type: Literal["Parameter Importance"] = "Parameter Importance"
    config: ParameterImportancePlotConfig


class RunComparerConfig(ReportAPIBaseModel):
    diff_only: Optional[Literal["split", True]] = None


class RunComparer(Panel):
    view_type: Literal["Run Comparer"] = "Run Comparer"
    config: RunComparerConfig


class QueryFieldsValue(ReportAPIBaseModel):
    name: str
    value: Any


class QueryFieldsField(ReportAPIBaseModel):
    name: str = ""
    fields: Optional[list["QueryFieldsField"]] = None
    # fields: list["QueryFieldsField"] = Field(default_factory=list)
    value: list[QueryFieldsValue] = Field(default_factory=list)


class QueryField(ReportAPIBaseModel):
    args: list[QueryFieldsValue] = Field(
        default_factory=lambda: [
            QueryFieldsValue(name="runSets", value="${runSets}"),
            QueryFieldsValue(name="limit", value=500),
        ]
    )
    fields: list[QueryFieldsField] = Field(
        default_factory=lambda: [
            QueryFieldsField(name="id", value=[], fields=None),
            QueryFieldsField(name="name", value=[], fields=None),
        ]
    )
    name: str = "runSets"


class UserQuery(ReportAPIBaseModel):
    query_fields: list[QueryField] = Field(default_factory=lambda: [QueryField()])


class Vega2ConfigTransform(ReportAPIBaseModel):
    name: Literal["tableWithLeafColNames"] = "tableWithLeafColNames"


class Vega2Config(ReportAPIBaseModel):
    transform: Vega2ConfigTransform = Field(default_factory=Vega2ConfigTransform)
    user_query: UserQuery = Field(default_factory=UserQuery)
    panel_def_id: str = ""
    field_settings: dict = Field(default_factory=dict)
    string_settings: dict = Field(default_factory=dict)


class Vega2(Panel):
    view_type: Literal["Vega2"] = "Vega2"
    config: Vega2Config = Field(default_factory=Vega2Config)


class UnknownPanel(ReportAPIBaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        # loc_by_alias=False,
        use_enum_values=True,
        validate_assignment=True,
        populate_by_name=True,
        arbitrary_types_allowed=True,
        extra="allow",
    )


class WeavePanel(Panel):
    view_type: Literal["Weave"] = "Weave"
    config: dict


def expr_to_filters(expr: str) -> Filters:
    # if not expr:
    #     return Filters(op="OR", filters=[Filters(op="AND", filters=[])])
    # parsed_expr = ast.parse(expr, mode="eval")
    # return _parse_node(parsed_expr.body)
    if not expr:
        filters = []
    else:
        parsed_expr = ast.parse(expr, mode="eval")
        filters = [_parse_node(parsed_expr.body)]

    return Filters(op="OR", filters=[Filters(op="AND", filters=filters)])


FUNCTION_TO_SECTION = {
    "Config": "config",
    "SummaryMetric": "summary",
    "KeysInfo": "keys_info",
    "Tags": "tags",
    "Metric": "runs",  # Adjust the actual section names as needed
}
SECTION_TO_FUNCTION = {v: k for k, v in FUNCTION_TO_SECTION.items()}


def _parse_node(node) -> Filters:
    if isinstance(node, ast.Compare):
        # Check if left side is a function call
        if isinstance(node.left, ast.Call):
            func_call_data = _handle_function_call(node.left)
            # Process the function call data
            if func_call_data:
                section = FUNCTION_TO_SECTION.get(
                    func_call_data["type"], "default_section"
                )
                key = Key(section=section, name=func_call_data["value"])
                # Construct the Filters object
                operation = _map_op(node.ops[0])
                right_operand = _extract_value(node.comparators[0])
                return Filters(
                    op=operation, key=key, value=right_operand, disabled=False
                )
        else:
            # Handle other cases, e.g., when left side is not a function call
            return _handle_comparison(node)
    elif isinstance(node, ast.BoolOp):
        return _handle_logical_op(node)
    else:
        raise ValueError(f"Unsupported expression type: {type(node)}")


def _map_op(op_node) -> str:
    # Map the AST operation node to a string representation
    op_map = {
        ast.Gt: ">",
        ast.Lt: "<",
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.GtE: ">=",
        ast.LtE: "<=",
        ast.In: "IN",
        ast.NotIn: "NIN",
    }
    return op_map[type(op_node)]


def _handle_comparison(node) -> Filters:
    left_operand = node.left.id if isinstance(node.left, ast.Name) else None
    left_operand_mapped = to_frontend_name(left_operand)
    right_operand = _extract_value(node.comparators[0])
    operation = type(node.ops[0]).__name__

    op_map = {
        "Gt": ">",
        "Lt": "<",
        "Eq": "==",
        "NotEq": "!=",
        "GtE": ">=",
        "LtE": "<=",
        "In": "IN",
        "NotIn": "NIN",
    }

    return Filters(
        op=op_map.get(operation),
        # key=Key(section="summary", name=left_operand_mapped)
        key=server_path_to_key(left_operand) if left_operand_mapped else None,
        value=right_operand,
        disabled=False,
    )


def _handle_function_call(node) -> dict:
    if isinstance(node.func, ast.Name):
        func_name = node.func.id
        if func_name in ["Config", "SummaryMetric", "KeysInfo", "Tags", "Metric"]:
            if len(node.args) == 1 and isinstance(node.args[0], ast.Str):
                arg_value = node.args[0].s
                # Return a dictionary with the function name and argument value
                return {"type": func_name, "value": arg_value}
            else:
                raise ValueError(f"Invalid arguments for {func_name}")
    else:
        raise ValueError("Unsupported function call")


def _extract_value(node) -> Any:
    if isinstance(node, ast.Constant):
        return node.n
    elif isinstance(node, ast.List) or isinstance(node, ast.Tuple):
        return [_extract_value(element) for element in node.elts]
    elif isinstance(node, ast.Name):
        # Return the variable name as a string
        return node.id
    else:
        raise ValueError(f"Unsupported value type: {type(node)}")


def _handle_logical_op(node) -> Filters:
    op = "AND" if isinstance(node.op, ast.And) else "OR"
    filters = [_parse_node(n) for n in node.values]

    return Filters(op=op, filters=filters)


def filters_to_expr(filter_obj: Any, is_root=True) -> str:
    op_map = {
        ">": ">",
        "<": "<",
        "=": "==",
        "!=": "!=",
        ">=": ">=",
        "<=": "<=",
        "IN": "in",
        "NIN": "not in",
        "AND": "and",
        "OR": "or",
    }

    def _convert_filter(filter: Any, is_root: bool) -> str:
        if hasattr(filter, "filters") and filter.filters is not None:
            sub_expressions = [
                _convert_filter(f, False)
                for f in filter.filters
                if f.filters is not None or (f.key and f.key.name)
            ]
            if not sub_expressions:
                return ""

            joint = " and " if filter.op == "AND" else " or "
            expr = joint.join(sub_expressions)
            return f"({expr})" if not is_root and sub_expressions else expr
        else:
            if not filter.key or not filter.key.name:
                # Skip filters with empty key names
                return ""

            key_name = filter.key.name
            section = filter.key.section

            # Prepend the function name if the section matches
            if section in SECTION_TO_FUNCTION:
                function_name = SECTION_TO_FUNCTION[section]
                key_name = f'{function_name}("{key_name}")'

            value = filter.value
            if value is None:
                value = "None"
            elif isinstance(value, list):
                value = f"[{', '.join(map(str, value))}]"
            elif isinstance(value, str):
                value = f"'{value}'"

            return f"{key_name} {op_map[filter.op]} {value}"

    return _convert_filter(filter_obj, is_root)


fe_name_mapping = {
    "ID": "name",
    "Name": "displayName",
    "Tags": "tags",
    "State": "state",
    "CreatedTimestamp": "createdAt",
    "Runtime": "duration",
    "User": "username",
    "Sweep": "sweep",
    "Group": "group",
    "JobType": "jobType",
    "Hostname": "host",
    "UsingArtifact": "inputArtifacts",
    "OutputtingArtifact": "outputArtifacts",
    "Step": "_step",
    "RelativeTime(Wall)": "_absolute_runtime",
    "RelativeTime(Process)": "_runtime",
    "WallTime": "_timestamp",
    # "GroupedRuns": "__wb_group_by_all"
}
reversed_fe_name_mapping = {v: k for k, v in fe_name_mapping.items()}

PanelTypes = Union[
    LinePlot,
    ScatterPlot,
    ScalarChart,
    BarPlot,
    CodeComparer,
    ParallelCoordinatesPlot,
    ParameterImportancePlot,
    RunComparer,
    MediaBrowser,
    MarkdownPanel,
    Vega2,
    WeavePanel,
    UnknownPanel,
]

BlockTypes = Union[
    Heading,
    Paragraph,
    CodeBlock,
    MarkdownBlock,
    LatexBlock,
    Image,
    List,
    CalloutBlock,
    Video,
    HorizontalRule,
    Spotify,
    SoundCloud,
    Gallery,
    PanelGrid,
    TableOfContents,
    BlockQuote,
    Twitter,
    UnknownBlock,
    # Block,
]

block_type_mapping = {
    "twitter": Twitter,
    "heading": Heading,
    "paragraph": Paragraph,
    "code-block": CodeBlock,
    "markdown-block": MarkdownBlock,
    "latex-block": LatexBlock,
    "image": Image,
    "list": List,
    "callout-block": CalloutBlock,
    "video": Video,
    "horziontal-rule": HorizontalRule,
    "spotify": Spotify,
    "soundcloud": SoundCloud,
    "gallery": Gallery,
    "panel-grid": PanelGrid,
    "table-of-contents": TableOfContents,
    "block-quote": BlockQuote,
}


def to_frontend_name(name):
    return reversed_fe_name_mapping.get(name, name)


def to_backend_name(name):
    return fe_name_mapping.get(name, name)


def is_valid_color(color_str: str) -> bool:
    # Regular expression for hex color validation
    hex_color_pattern = r"^#(?:[0-9a-fA-F]{3}){1,2}$"

    # Check if it's a valid hex color
    if re.match(hex_color_pattern, color_str):
        return True

    # Try parsing it as an RGB or RGBA tuple
    try:
        # Strip 'rgb(' or 'rgba(' and the closing ')'
        if color_str.startswith("rgb(") and color_str.endswith(")"):
            parts = color_str[4:-1].split(",")
        elif color_str.startswith("rgba(") and color_str.endswith(")"):
            parts = color_str[5:-1].split(",")
        else:
            return False

        # Convert parts to integers and validate ranges
        parts = [int(p.strip()) for p in parts]
        if len(parts) == 3 and all(0 <= p <= 255 for p in parts):
            return True  # Valid RGB
        if (
            len(parts) == 4
            and all(0 <= p <= 255 for p in parts[:-1])
            and 0 <= parts[-1] <= 1
        ):
            return True  # Valid RGBA

    except ValueError:
        pass

    return False


def key_to_server_path(key: Key):
    name = key.name
    if (section := key.section) == "config":
        return f"config.{name}"
    elif section == "summary":
        return f"summary_metrics.{name}"
    elif section == "keys_info":
        return f"keys_info.keys.{name}"
    elif section == "tags":
        return f"tags.{name}"
    elif section == "runs":
        return name
    raise ValueError(f"Invalid {key=}")


def server_path_to_key(path):
    if path.startswith("config."):
        return Key(section="config", name=path.split("config.", 1)[1])
    elif path.startswith("summary_metrics."):
        return Key(section="summary", name=path.split("summary_metrics.", 1)[1])
    elif path.startswith("keys_info.keys."):
        return Key(section="keys_info", name=path.split("keys_info.keys.", 1)[1])
    elif path.startswith("tags."):
        return Key(section="tags", name=path.split("tags.", 1)[1])
    else:
        return Key(section="run", name=path)


class CustomNodeVisitor(ast.NodeVisitor):
    def visit_Compare(self, node):  # noqa: N802
        left = self.handle_expression(node.left)
        print(f"Expression type: {left}")
        # Continue to handle the comparison operators and right side as needed
        self.generic_visit(node)

    def handle_expression(self, node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in ["Config", "SummaryMetric", "KeysInfo", "Tags", "Metric"]:
                if len(node.args) == 1 and isinstance(node.args[0], ast.Str):
                    arg_value = node.args[0].s
                    return func_name, arg_value
        return self.get_full_expression(node)

    def get_full_expression(self, node):
        if isinstance(node, ast.Attribute):
            return self.get_full_expression(node.value) + "." + node.attr
        elif isinstance(node, ast.Name):
            return node.id
        else:
            return "ArbitraryExpression"
