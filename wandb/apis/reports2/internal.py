"""All of the serde stuff lives here."""

from datetime import datetime
from typing import Literal, Optional, Union

from pydantic import AnyUrl, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

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
Range = Union[list[Optional[float]], tuple[Optional[float], Optional[float]]]


class ReportAPIBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        # loc_by_alias=False,
        use_enum_values=True,
        validate_assignment=True,
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )


class Ref(ReportAPIBaseModel):
    type: str = "panel"
    view_id: str = ""
    id: str = ""


class Text(ReportAPIBaseModel):
    text: str = ""


class Project(ReportAPIBaseModel):
    # id: str
    name: str
    entity_name: str = Field(..., alias="entityName")


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
    ref: dict = Field(default_factory=dict)


class PanelBankConfigSection(ReportAPIBaseModel):
    name: Literal["Hidden Panels"] = "Hidden Panels"
    is_open: bool = False
    type: str = "flow"
    flow_config: FlowConfig = Field(default_factory=Field)
    sorted: int = 0
    local_panel_settings: LocalPanelSettings = Field(default_factory=LocalPanelSettings)


class PanelBankConfig(ReportAPIBaseModel):
    state: int = 0
    settings: dict = Field(default_factory=PanelBankConfigSettings)
    sections: list[dict] = Field(default_factory=list)


class PanelBankConfigSectionsItem(ReportAPIBaseModel):
    name: str = "Hidden Panels"
    is_open: bool = False
    type: str = "flow"
    flow_config: FlowConfig = Field(default_factory=FlowConfig)
    sorted: int = 0
    local_panel_settings: LocalPanelSettings = Field(default_factory=LocalPanelSettings)
    panels: list = Field(default_factory=list)
    local_panel_settings_ref: dict = Field(default_factory=dict)
    panel_refs: list = Field(default_factory=list)
    ref: dict = Field(default_factory=dict)


class PanelBankSectionConfig(ReportAPIBaseModel):
    name: Literal["Report Panels"] = "Report Panels"
    is_open: bool = False
    panels: list = Field(default_factory=list)
    type: Literal["grid"] = "grid"
    flow_config: dict = Field(default_factory=dict)
    sorted: int = 0
    local_panel_settings: dict = Field(default_factory=dict)


class PanelGridCustomRunColors(ReportAPIBaseModel):
    ref: Ref


class PanelGridMetadata(ReportAPIBaseModel):
    open_viz: bool = True
    open_run_set: Optional[str] = None  # none is closed
    name: Literal["unused-name"] = "unused-name"
    run_sets: list = Field(default_factory=list)
    panels: dict = Field(default_factory=dict)
    panel_bank_config: PanelBankConfig = Field(default_factory=PanelBankConfig)
    panel_bank_section_config: PanelBankSectionConfig = Field(
        default_factory=PanelBankSectionConfig
    )
    custom_run_colors: PanelGridCustomRunColors = Field(
        default_factory=PanelGridCustomRunColors
    )


class Block(ReportAPIBaseModel):
    ...


class PanelGrid(Block):
    type: Literal["panel-grid"] = "panel-grid"
    children: list = Field(default_factory=lambda: [Text()])
    metadata: PanelGridMetadata = Field(default_factory=PanelGridMetadata)


class RunsetSearch(ReportAPIBaseModel):
    query: str = ""


class RunFeed(ReportAPIBaseModel):
    version: int = 2
    column_visible: dict
    column_pinned: dict
    column_widths: dict
    column_order: list
    page_size: int = 10
    only_show_selected: bool


class Runset(ReportAPIBaseModel):
    id: str
    run_feed: RunFeed
    enabled: bool
    project: Project
    name: str = ""
    search: RunsetSearch = Field(default_factory=RunsetSearch)
    filters: dict = Field(default_factory=dict)
    grouping: list = Field(default_factory=list)
    sort: list = Field(default_factory=list)
    selections: dict
    expanded_row_addresses: list
    ref: Ref


class CodeLine(ReportAPIBaseModel):
    type: Literal["code-line"] = "code-line"
    children: list[Text]
    language: str


class Heading(Block):
    type: Literal["heading"] = "heading"
    children: list[Text] = Field(default_factory=lambda: [Text()])
    collapsed_children: Optional[list["BlockTypes"]] = None
    level: int


class Paragraph(Block):
    type: Literal["paragraph"] = "paragraph"
    children: list[Text] = Field(default_factory=lambda: [Text()])


class CodeBlock(Block):
    type: Literal["code-block"] = "code-block"
    children: list[CodeLine]
    language: str


class MarkdownBlock(Block):
    type: Literal["markdown-block"] = "markdown-block"
    children: list[Text] = Field(default_factory=lambda: [Text()])
    content: str


class LatexBlock(Block):
    type: Literal["latex"] = "latex"
    children: list[Text]
    content: str
    block: bool = True


class Image(Block):
    type: Literal["image"] = "image"
    children: list[Text]
    url: AnyUrl
    has_caption: bool


class ListItem(ReportAPIBaseModel):
    type: Literal["list-item"] = "list-item"
    children: list[Paragraph]
    ordered: Optional[Literal[True]] = None
    checked: Optional[bool] = None


class List(Block):
    type: Literal["list"] = "list"
    children: list[ListItem]
    ordered: Optional[Literal[True]] = None


class CalloutLine(ReportAPIBaseModel):
    type: Literal["callout-line"] = "callout-line"
    children: list[Text]


class BlockQuote(Block):
    type: Literal["callout-block"] = "callout-block"
    children: list[CalloutLine]


class HorizontalRule(Block):
    type: Literal["horizontal-rule"] = "horizontal-rule"
    children: list[Text] = Field(default_factory=lambda: [Text()])


class Video(Block):
    type: Literal["video"] = "video"
    url: AnyUrl
    children: list[Text] = Field(default_factory=lambda: [Text()])


class Spotify(Block):
    type: Literal["spotify"] = "spotify"
    spotify_type: Literal["track"] = "track"
    spotify_id: str = Field(..., alias="spotifyID")
    children: list[Text] = Field(default_factory=lambda: [Text()])


class SoundCloud(Block):
    type: Literal["soundcloud"] = "soundcloud"
    html: str
    children: list[Text]


class Gallery(Block):
    type: Literal["gallery"] = "gallery"
    children: list[Text] = Field(default_factory=lambda: [Text()])
    ids: list[str]


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


BlockTypes = Union[
    Heading,
    Paragraph,
    CodeBlock,
    MarkdownBlock,
    LatexBlock,
    Image,
    List,
    BlockQuote,
    Video,
    HorizontalRule,
    Spotify,
    SoundCloud,
    Gallery,
    Block,
]


class Spec(ReportAPIBaseModel):
    version: int = 5
    panel_settings: dict = Field(default_factory=dict)
    blocks: list[BlockTypes] = Field(default_factory=list)
    width: str = "readable"
    authors: list = Field(default_factory=list)
    discussion_threads: list = Field(default_factory=list)
    ref: dict = Field(default_factory=dict)


class ReportViewspec(ReportAPIBaseModel):
    id: str = ""
    name: str = ""
    display_name: str
    description: str
    project: Project
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    spec: Spec = Field(default_factory=Spec)


class Layout(ReportAPIBaseModel):
    x: int = 0
    y: int = 0
    w: int = 8
    h: int = 6


class MediaBrowserConfig(ReportAPIBaseModel):
    column_count: Optional[int] = None
    media_keys: list[str] = Field(default_factory=list)


class Panel(ReportAPIBaseModel):
    id: str = Field("", alias="__id__")
    layout: Layout = Field(default_factory=Layout)
    ref: Ref = Field(default_factory=Ref)


class MediaBrowser(Panel):
    view_type: Literal["Media Browser"] = "Media Browser"
    config: MediaBrowserConfig


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
    x_log_scale: Optional[Literal[True]] = None
    y_log_scale: Optional[Literal[True]] = None
    x_axis_title: Optional[str] = None
    y_axis_title: Optional[str] = None
    ignore_outliers: Optional[Literal[True]] = None
    group_by: Optional[str] = None
    group_agg: Optional[GroupAgg] = None
    group_area: Optional[GroupArea] = None
    smoothing_weight: Optional[float] = None
    smoothing_type: Optional[SmoothingType] = None
    show_original_after_smoothing: Optional[Literal[True]] = None
    limit: Optional[int] = None
    expressions: Optional[str] = None
    plot_type: Optional[LinePlotStyle] = None
    font_size: Optional[FontSize] = None
    legend_position: Optional[LegendPosition] = None
    legend_template: Optional[str] = None
    aggregate: Optional[bool] = None
    x_expression: Optional[str] = None

    # there are more here...


class LinePlot(Panel):
    view_type: Literal["Run History Line Plot"] = "Run History Line Plot"
    config: LinePlotConfig


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
    x_axis_log_scale: Optional[Literal[True]] = None
    y_axis_log_scale: Optional[Literal[True]] = None
    z_axis_log_scale: Optional[Literal[True]] = None
    show_min_y_axis_line: Optional[Literal[True]] = None
    show_max_y_axis_line: Optional[Literal[True]] = None
    show_avg_y_axis_line: Optional[Literal[True]] = None
    legend_template: Optional[str] = None
    custom_gradient: Optional[dict] = None
    font_size: Optional[FontSize] = None
    show_linear_regression: Optional[Literal[True]] = None


class ScatterPlot(Panel):
    view_type: Literal["Scatter Plot"] = "Scatter Plot"
    config: ScatterPlotConfig


class BarPlotConfig(ReportAPIBaseModel):
    chart_title: Optional[str] = None
    metrics: list[str] = Field(default_factory=list)
    vertical: bool = False
    x_axis_min: Optional[float]
    x_axis_max: Optional[float]
    x_axis_title: Optional[str]
    y_axis_title: Optional[str]
    group_by: Optional[str]
    group_agg: Optional[GroupAgg]
    group_area: Optional[GroupArea]
    limit: Optional[int]
    bar_limit: Optional[int]
    expressions: Optional[str]
    legend_template: Optional[str]
    font_size: Optional[FontSize]
    override_series_titles: Optional[str]
    override_colors: Optional[str]


class BarPlot(Panel):
    view_type: Literal["Bar Chart"] = "Bar Chart"
    config: BarPlotConfig


class ScalarChartConfig(ReportAPIBaseModel):
    chart_title: Optional[str]
    metrics: list[str]
    group_agg: Optional[GroupAgg]
    group_area: Optional[GroupArea]
    expressions: Optional[str]
    legend_template: Optional[str]
    font_size: Optional[FontSize]


class ScalarChart(Panel):
    view_type: Literal["Scalar Chart"] = "Scalar Chart"
    config: ScalarChartConfig


class CodeComparerConfig(ReportAPIBaseModel):
    diff: CodeCompareDiff


class CodeComparer(Panel):
    view_type: Literal["Code Comparer"] = "Code Comparer"
    config: CodeComparerConfig


class Column(ReportAPIBaseModel):
    accessor: str
    display_name: Optional[str]
    inverted: Optional[Literal[True]]
    log: Optional[Literal[True]]


class ParallelCoordinatesPlotConfig(ReportAPIBaseModel):
    chart_title: Optional[str]
    columns: list[Column]
    font_size: Optional[FontSize]


class ParallelCoordinatesPlot(Panel):
    view_type: Literal["Parallel Coordinates Plot"] = "Parallel Coordinates Plot"
    config: ParallelCoordinatesPlotConfig


class ParameterConf(ReportAPIBaseModel):
    version: int = 2
    column_visible: dict = Field(default_factory=dict)


class ParameterImportancePlotConfig(ReportAPIBaseModel):
    target_key: str
    parameter_conf: ParameterConf
    columns_pinned: dict
    column_widths: dict
    column_order: list[str]
    page_size: int
    only_show_selected: bool


class ParameterImportancePlot(Panel):
    view_type: Literal["Parameter Importance"] = "Parameter Importance"
    config: ParameterImportancePlotConfig


class RunComparerConfig(ReportAPIBaseModel):
    diff_only: Optional[Literal["split"]] = None


class RunComparer(Panel):
    view_type: Literal["Run Comparer"] = "Run Comparer"
    config: RunComparerConfig


class QueryFieldsArg(ReportAPIBaseModel):
    name: str
    value: Union[str, list[str]]


class QueryFieldsField(ReportAPIBaseModel):
    name: str
    fields: list["QueryFieldsField"]
    args: list[QueryFieldsArg]


class QueryField(ReportAPIBaseModel):
    name: str
    fields: list[QueryFieldsField]
    args: list[QueryFieldsArg]


class UserQuery(ReportAPIBaseModel):
    query_fields: list[QueryField]


class Vega2ConfigTransform(ReportAPIBaseModel):
    name: str


class Vega2Config(ReportAPIBaseModel):
    transform: Vega2ConfigTransform
    user_query: UserQuery


class Vega2(Panel):
    view_type: Literal["Vega2"] = "Vega2"
    config: Vega2Config


class Weave(Panel):
    view_type: Literal["Weave"] = "Weave"
    config: dict
