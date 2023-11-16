from typing import Iterable, List, Literal, Optional, Union
from typing import List as LList

from pydantic import AnyUrl, ConfigDict, Field
from pydantic.dataclasses import dataclass, rebuild_dataclass

import wandb

from . import internal
from .internal import (
    CodeCompareDiff,
    FontSize,
    GroupAgg,
    GroupArea,
    LegendPosition,
    LinePlotStyle,
    Range,
    SmoothingType,
)

_api = wandb.Api()
DEFAULT_ENTITY = _api.default_entity

report_api_dataclass = dataclass(
    config=ConfigDict(validate_assignment=True, extra="forbid", slots=True)
)


@report_api_dataclass
# @dataclasses.dataclass
class Base:
    def __repr__(self):
        fields = ", ".join(
            f"{k}={v!r}" for k, v in self.__dict__.items() if not none_or_empty(v)
        )
        return f"{self.__class__.__name__}({fields})"


@report_api_dataclass
class Layout(Base):
    x: int = 0
    y: int = 0
    w: int = 8
    h: int = 6

    def to_model(self):
        return internal.Layout(x=self.x, y=self.y, w=self.w, h=self.h)

    @classmethod
    def from_model(cls, model: internal.Layout):
        return cls(x=model.x, y=model.y, w=model.w, h=model.h)


@report_api_dataclass
class Report(Base):
    project: str
    entity: str = DEFAULT_ENTITY
    title: str = "Untitled Report"
    description: str = ""

    blocks: List["BlockTypes"] = Field(default_factory=list)

    def to_model(self):
        return internal.ReportViewspec(
            display_name=self.title,
            description=self.description,
            project=internal.Project(name=self.project, entity_name=self.entity),
            spec=internal.Spec(blocks=[b.to_model() for b in self.blocks]),
        )

    @classmethod
    def from_model(cls, model: internal.ReportViewspec):
        return cls(
            title=model.display_name,
            description=model.description,
            entity=model.project.entity_name,
            project=model.project.name,
            # blocks=[lookup(b) for b in model.spec.blocks],
            blocks=[lookup(b) for b in model.spec.blocks],
        )

    def save(self, draft: bool = False, clone: bool = False):
        model = self.to_model()

        return self

        # r = self._api.client.execute(
        #     UPSERT_VIEW,
        #     variable_values={
        #         "id": None if clone or not self.id else self.id,
        #         "name": generate_name() if clone or not self.name else self.name,
        #         "entityName": self.entity,
        #         "projectName": self.project,
        #         "description": self.description,
        #         "displayName": self.title,
        #         "type": "runs/draft" if draft else "runs",
        #         "spec": model.spec.model_dump_json(),
        #     },
        # )


@report_api_dataclass
class Block(Base):
    ...

    def __repr__(self):
        fields = ", ".join(
            f"{k}={v!r}" for k, v in self.__dict__.items() if not none_or_empty(v)
        )
        return f"{self.__class__.__name__}({fields})"

    # @classmethod
    # def from_model(cls, model: internal.BlockTypes):
    #     cls = block_mapping.get(model.__class__)
    #     return cls.from_model(model)


@report_api_dataclass
class Heading(Block):
    @classmethod
    def from_model(cls, model: internal.Heading):
        texts = [text.text for text in model.children]
        text = "\n".join(texts)

        blocks = None
        if model.collapsed_children:
            blocks = [lookup(b) for b in model.collapsed_children]

        if model.level == 1:
            return H1(text=text, blocks=blocks)
        if model.level == 2:
            return H2(text=text, blocks=blocks)
        if model.level == 3:
            return H3(text=text, blocks=blocks)


@report_api_dataclass
class List(Block):
    @classmethod
    def from_model(cls, model: internal.List):
        if not model.children:
            return UnorderedList()

        item = model.children[0]
        if item.ordered is not None:
            list_items = []
            for item in model.children:
                for p in item.children:
                    texts = [text.text for text in p.children]
                text = "".join(texts)
                list_item = OrderedListItem(text=text)
                list_items.append(list_item)
            return OrderedList(items=list_items)

        if item.checked is not None:
            list_items = []
            for item in model.children:
                for p in item.children:
                    texts = [text.text for text in p.children]
                text = "".join(texts)
                checked = item.checked
                list_item = CheckedListItem(text=text, checked=checked)
                list_items.append(list_item)
            return CheckedList(items=list_items)

        list_items = []
        for item in model.children:
            for p in item.children:
                texts = [text.text for text in p.children]
            text = "".join(texts)
            list_item = UnorderedListItem(text=text)
            list_items.append(list_item)
        return UnorderedList(items=list_items)


@report_api_dataclass
class H1(Heading):
    text: str
    collapsed_blocks: Optional[list["BlockTypes"]] = None

    def to_model(self):
        if (collapsed_children := self.collapsed_blocks) is not None:
            collapsed_children = [b.to_model() for b in collapsed_children]

        return internal.Heading(
            level=1,
            children=[internal.Text(text=self.text)],
            collapsed_children=collapsed_children,
        )


@report_api_dataclass
class H2(Block):
    text: str
    collapsed_blocks: Optional[list["BlockTypes"]] = None

    def to_model(self):
        if (collapsed_children := self.collapsed_blocks) is not None:
            collapsed_children = [b.to_model() for b in collapsed_children]

        return internal.Heading(
            level=2,
            children=[internal.Text(text=self.text)],
            collapsed_children=collapsed_children,
        )


@report_api_dataclass
class H3(Block):
    text: str
    collapsed_blocks: Optional[list["BlockTypes"]] = None

    def to_model(self):
        if (collapsed_children := self.collapsed_blocks) is not None:
            collapsed_children = [b.to_model() for b in collapsed_children]

        return internal.Heading(
            level=3,
            children=[internal.Text(text=self.text)],
            collapsed_children=collapsed_children,
        )


@report_api_dataclass
class P(Block):
    text: str

    def to_model(self):
        return internal.Paragraph(children=[internal.Text(text=self.text)])

    @classmethod
    def from_model(cls, model: internal.Paragraph):
        texts = [text.text for text in model.children]
        text = "\n".join(texts)
        return cls(text=text)


@report_api_dataclass
class CheckedListItem:
    text: str
    checked: bool = False

    def to_model(self):
        return internal.ListItem(
            children=[internal.Paragraph(children=[internal.Text(text=self.text)])],
            checked=self.checked,
        )


@report_api_dataclass
class OrderedListItem:
    text: str

    def to_model(self):
        return internal.ListItem(
            children=[internal.Paragraph(children=[internal.Text(text=self.text)])],
            ordered=True,
        )


@report_api_dataclass
class UnorderedListItem:
    text: str

    def to_model(self):
        return internal.ListItem(
            children=[internal.Paragraph(children=[internal.Text(text=self.text)])],
        )


@report_api_dataclass
class CheckedList(List):
    items: LList[CheckedListItem]

    def to_model(self):
        items = [x.to_model() for x in self.items]
        return internal.List(children=items)


@report_api_dataclass
class OrderedList(List):
    items: LList[OrderedListItem]

    def to_model(self):
        items = [x.to_model() for x in self.items]
        return internal.List(children=items)


@report_api_dataclass
class UnorderedList(List):
    items: LList[UnorderedListItem]

    def to_model(self):
        items = [x.to_model() for x in self.items]
        return internal.List(children=items)


@report_api_dataclass
class CodeBlock(Block):
    code: str
    language: str

    def to_model(self):
        return internal.CodeBlock(
            children=[
                internal.CodeLine(
                    children=[internal.Text(text=self.code)],
                    language=self.language,
                )
            ],
            language=self.language,
        )

    @classmethod
    def from_model(cls, model: internal.CodeBlock):
        texts = [text.text for line in model.children for text in line.children]
        text = "\n".join(texts)
        return cls(code=text, language=model.language)


@report_api_dataclass
class MarkdownBlock(Block):
    text: str

    def to_model(self):
        return internal.MarkdownBlock(content=self.text)

    @classmethod
    def from_model(cls, model: internal.MarkdownBlock):
        return cls(text=model.content)


@report_api_dataclass
class LatexBlock(Block):
    text: str

    def to_model(self):
        return internal.LatexBlock(content=self.text)

    @classmethod
    def from_model(cls, model: internal.LatexBlock):
        return cls(text=model.content)


@report_api_dataclass
class Image(Block):
    # TODO: fix captions
    url: AnyUrl
    caption: Optional[str]

    def to_model(self):
        return internal.Image(
            children=[internal.Text(text=self.caption)],
            url=self.url,
        )

    @classmethod
    def from_model(cls, model: internal.Image):
        return internal.Image(url=model.url)


@report_api_dataclass
class BlockQuote(Block):
    text: str

    def to_model(self):
        return internal.BlockQuote(
            children=[internal.CalloutLine(children=[internal.Text(text=self.text)])]
        )

    @classmethod
    def from_model(cls, model: internal.BlockQuote):
        texts = [text.text for line in model.children for text in line.children]
        text = "\n".join(texts)
        return cls(text=text)


@report_api_dataclass
class HorizontalRule(Block):
    def to_model(self):
        return internal.HorizontalRule()

    @classmethod
    def from_model(cls, model: internal.HorizontalRule):
        return cls()


@report_api_dataclass
class Video(Block):
    url: AnyUrl

    def to_model(self):
        return internal.Video(url=self.url)

    @classmethod
    def from_model(cls, model: internal.Video):
        return cls(url=model.url)


@report_api_dataclass
class Spotify(Block):
    spotify_id: str

    def to_model(self):
        return internal.Spotify(spotify_id=self.spotify_id)

    @classmethod
    def from_model(cls, model: internal.Spotify):
        return cls(spotify_id=model.spotify_id)


@report_api_dataclass
class SoundCloud(Block):
    html: str

    def to_model(self):
        return internal.SoundCloud(html=self.html)

    @classmethod
    def from_model(cls, model: internal.SoundCloud):
        return cls(html=model.html)


@report_api_dataclass
class Gallery(Block):
    ids: list[str]

    def to_model(self):
        return internal.Gallery(ids=self.ids)

    @classmethod
    def from_model(cls, model: internal.Gallery):
        return cls(ids=model.ids)


@report_api_dataclass
class CustomRunColors:
    ...


@report_api_dataclass
class Runset(Base):
    entity: Optional[str] = None
    project: Optional[str] = None
    name: str = "Run set"
    query: str = ""
    filters: dict = Field(default_factory=lambda: {"$or": [{"$and": []}]})
    groupby: list = Field(default_factory=list)
    order: list = Field(default_factory=lambda: ["-CreatedTimestamp"])

    def to_model(self):
        return internal.Runset(
            project=internal.Project(entity_name=self.entity, name=self.project),
            name=self.name,
            filters=self.filters,
            grouping=self.groupby,
            sort=self.order,
        )

    @classmethod
    def from_model(cls, model: internal.Runset):
        return cls(
            entity=model.project.entity_name,
            project=model.project.name,
            name=model.name,
            filters=model.filters,
            groupby=model.grouping,
            order=model.sort,
        )


@report_api_dataclass
# @dataclasses.dataclass
class Panel(Base):
    layout: Layout = Field(default_factory=Layout)


@report_api_dataclass
class PanelGrid(Block):
    runsets: list[Runset] = Field(default_factory=list)
    panels: list[Panel] = Field(default_factory=list)
    custom_run_colors: Optional[CustomRunColors] = None
    active_runset: Optional[str] = None

    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.PanelGrid):
        ...


@report_api_dataclass
class TableOfContents(Block):
    ...


@report_api_dataclass
class Twitter(Block):
    ...


@report_api_dataclass
class WeaveBlock(Block):
    ...


BlockTypes = Union[
    H1,
    H2,
    H3,
    P,
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

block_mapping = {
    internal.Paragraph: P,
    internal.BlockQuote: BlockQuote,
    internal.CodeBlock: CodeBlock,
    internal.Gallery: Gallery,
    internal.Heading: Heading,
    internal.HorizontalRule: HorizontalRule,
    internal.Image: Image,
    internal.LatexBlock: LatexBlock,
    internal.List: List,
    internal.MarkdownBlock: MarkdownBlock,
    internal.PanelGrid: PanelGrid,
    internal.TableOfContents: TableOfContents,
    internal.Video: Video,
    internal.Spotify: Spotify,
    internal.Twitter: Twitter,
    internal.SoundCloud: SoundCloud,
}


@report_api_dataclass
class CustomRunColors:
    ...


@report_api_dataclass
class LinePlot(Panel):
    title: Optional[str] = None
    x: Optional[str] = None
    y: Union[list[str], str] = ""
    range_x: Range = Field(default_factory=lambda: (None, None))
    range_y: Range = Field(default_factory=lambda: (None, None))
    log_x: Optional[Literal[True]] = None
    log_y: Optional[Literal[True]] = None
    title_x: Optional[str] = None
    title_y: Optional[str] = None
    ignore_outliers: Optional[Literal[True]] = None
    groupby: Optional[str] = None
    groupby_aggfunc: Optional[GroupAgg] = None
    groupby_rangefunc: Optional[GroupArea] = None
    smoothing_factor: Optional[float] = None
    smoothing_type: Optional[SmoothingType] = None
    smoothing_show_original: Optional[bool] = None
    max_runs_to_show: Optional[int] = None
    custom_expressions: Optional[str] = None
    plot_type: Optional[LinePlotStyle] = None
    font_size: Optional[FontSize] = None
    legend_position: Optional[LegendPosition] = None
    legend_template: Optional[str] = None
    aggregate: Optional[bool] = None
    xaxis_expression: Optional[str] = None

    def to_model(self):
        return internal.LinePlot(
            layout=internal.Layout(
                x=self.layout.x, y=self.layout.y, w=self.layout.w, h=self.layout.h
            ),
            config=internal.LinePlotConfig(
                chart_title=self.title,
                x_axis=self.x,
                metrics=listify(self.y),
                x_axis_min=self.range_x[0],
                x_axis_max=self.range_x[1],
                y_axis_min=self.range_x[0],
                y_axis_max=self.range_x[1],
                x_log_scale=self.log_x,
                y_log_scale=self.log_y,
                x_axis_title=self.title_x,
                y_axis_title=self.title_y,
                ignore_outliers=self.ignore_outliers,
                group_by=self.groupby,
                group_agg=self.groupby_aggfunc,
                group_area=self.groupby_rangefunc,
                smoothing_weight=self.smoothing_factor,
                smoothing_type=self.smoothing_type,
                show_original_after_smoothing=self.smoothing_show_original,
                limit=self.max_runs_to_show,
                expressions=self.custom_expressions,
                plot_type=self.plot_type,
                font_size=self.font_size,
                legend_position=self.legend_position,
                legend_template=self.legend_template,
                aggregate=self.aggregate,
                x_expression=self.xaxis_expression,
            ),
        )

    @classmethod
    def from_model(cls, model: internal.LinePlot):
        return cls(
            title=model.config.chart_title,
            x=model.config.x_axis,
            y=model.config.metrics,
            range_x=(model.config.x_axis_min, model.config.x_axis_max),
            range_y=(model.config.y_axis_min, model.config.y_axis_max),
            log_x=model.config.x_log_scale,
            log_y=model.config.y_log_scale,
            title_x=model.config.x_axis_title,
            title_y=model.config.y_axis_title,
            ignore_outliers=model.config.ignore_outliers,
            groupby=model.config.group_by,
            groupby_aggfunc=model.config.group_agg,
            groupby_rangefunc=model.config.group_area,
            smoothing_factor=model.config.smoothing_weight,
            smoothing_type=model.config.smoothing_type,
            smoothing_show_original=model.config.show_original_after_smoothing,
            max_runs_to_show=model.config.limit,
            custom_expressions=model.config.expressions,
            plot_type=model.config.plot_type,
            font_size=model.config.font_size,
            legend_position=model.config.legend_position,
            legend_template=model.config.legend_template,
            aggregate=model.config.aggregate,
            xaxis_expression=model.config.x_expression,
        )


@report_api_dataclass
class ScatterPlot(Panel):
    title: Optional[str] = None
    x: Optional[str] = None
    y: Optional[str] = None
    z: Optional[str] = None
    range_x: Range = Field(default_factory=lambda: (None, None))
    range_y: Range = Field(default_factory=lambda: (None, None))
    range_z: Range = Field(default_factory=lambda: (None, None))
    log_x: Optional[bool] = None
    log_y: Optional[bool] = None
    log_z: Optional[bool] = None
    running_ymin: Optional[bool] = None
    running_ymax: Optional[bool] = None
    running_ymean: Optional[bool] = None
    legend_template: Optional[str] = None
    gradient: Optional[dict] = None
    font_size: Optional[FontSize] = None
    regression: Optional[bool] = None

    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class BarPlot(Panel):
    title: Optional[str] = None
    metrics: Optional[list[str]] = None
    orientation: str = "v"
    range_x: Range = Field(default_factory=lambda: (None, None))
    title_x: Optional[str] = None
    title_y: Optional[str] = None
    groupby: Optional[str] = None
    groupby_aggfunc: Optional[GroupAgg] = None
    groupby_rangefunc: Optional[GroupArea] = None
    max_runs_to_show: Optional[int] = None
    max_bars_to_show: Optional[int] = None
    custom_expressions: Optional[str] = None
    legend_template: Optional[str] = None
    font_size: Optional[FontSize] = None
    line_titles: Optional[dict] = None
    line_colors: Optional[dict] = None

    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class ScalarChart(Panel):
    title: Optional[str] = None
    metric: str = ""
    groupby_aggfunc: Optional[GroupAgg] = None
    groupby_rangefunc: Optional[GroupArea] = None
    custom_expressions: Optional[str] = None
    legend_template: Optional[str] = None
    font_size: Optional[FontSize] = None

    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class CodeComparer(Panel):
    diff: Optional[CodeCompareDiff] = None

    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class ParallelCoordinatesPlotColumn:
    ...


@report_api_dataclass
class ParallelCoordinatesPlot(Panel):
    columns: list[ParallelCoordinatesPlotColumn] = Field(default_factory=list)
    title: Optional[str] = None
    gradient: Optional[list] = None
    font_size: Optional[FontSize] = None

    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class ParameterImportancePlot(Panel):
    with_respect_to: str = ""

    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class RunComparer(Panel):
    diff_only: Optional[Literal["split"]] = None

    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class MediaBrowser(Panel):
    num_columns: Optional[int] = None
    media_keys: Optional[list[str]] = None

    def to_model(self):
        return internal.MediaBrowser(
            config=internal.MediaBrowserConfig(
                column_count=self.num_columns,
                media_keys=self.media_keys,
            ),
            layout=self.layout.to_model(),
        )

    @classmethod
    def from_model(cls, model: internal.MediaBrowser):
        return cls(
            num_columns=model.config.column_count,
            media_keys=model.config.media_keys,
            layout=Layout.from_model(model.layout),
        )


@report_api_dataclass
class MarkdownPanel(Panel):
    markdown: Optional[str] = None

    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class ConfusionMatrix(Panel):
    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class DataFrames(Panel):
    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class MultiRunTable(Panel):
    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class Vega(Panel):
    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class CustomChart(Panel):
    query: dict = Field(default_factory=dict)
    chart_name: str = Field(default_factory=dict)
    chart_fields: dict = Field(default_factory=dict)
    chart_strings: dict = Field(default_factory=dict)

    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class Vega3(Panel):
    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@report_api_dataclass
class WeavePanel(Panel):
    ...


def lookup(block):
    # print(block)
    cls = block_mapping.get(block.__class__)
    return cls.from_model(block)


def none_or_empty(v):
    if v is None:
        return True
    if isinstance(v, Iterable) and not isinstance(v, (str, bytes, bytearray)):
        return all(x is None for x in v)
    return False


def listify(x):
    if isinstance(x, Iterable):
        return list(x)
    return [x]


rebuild_dataclass(LinePlot, force=True)
