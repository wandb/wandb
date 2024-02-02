"""Public interfaces for the Report API."""
import os
from datetime import datetime
from typing import Dict, Iterable, Optional, Tuple, Union
from typing import List as LList

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

from urllib.parse import urlparse, urlunparse

from pydantic import ConfigDict, Field, validator
from pydantic.dataclasses import dataclass

import wandb

from . import expr_parsing, gql, internal
from .internal import (
    CodeCompareDiff,
    FontSize,
    GroupAgg,
    GroupArea,
    Language,
    LegendPosition,
    LinePlotStyle,
    Range,
    ReportWidth,
    SmoothingType,
)

TextLike = Union[str, "TextWithInlineComments", "Link", "InlineLatex", "InlineCode"]
TextLikeField = Union[TextLike, LList[TextLike]]
SpecialMetricType = Union["Config", "SummaryMetric", "Metric"]
MetricType = Union[str, SpecialMetricType]
ParallelCoordinatesMetric = Union[str, "Config", "SummaryMetric"]
RunId = str


dataclass_config = ConfigDict(validate_assignment=True, extra="forbid", slots=True)


@dataclass(config=dataclass_config)
class Base:
    ...
    # TODO: Add __repr__ that hides Nones

    @property
    def _model(self):
        return self.to_model()

    @property
    def _spec(self):
        return self._model.model_dump(by_alias=True, exclude_none=True)


@dataclass(config=dataclass_config, frozen=True)
class RunsetGroupKey:
    key: MetricType
    value: str


@dataclass(config=dataclass_config, frozen=True)
class RunsetGroup:
    runset_name: str
    keys: Tuple[RunsetGroupKey, ...]


@dataclass(config=dataclass_config, frozen=True)
class Metric:
    name: str


@dataclass(config=dataclass_config, frozen=True)
class Config:
    name: str


@dataclass(config=dataclass_config, frozen=True)
class SummaryMetric:
    name: str


@dataclass(config=dataclass_config)
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


@dataclass(config=dataclass_config)
class Block(Base):
    ...


@dataclass(config=ConfigDict(validate_assignment=True, extra="allow", slots=True))
class UnknownBlock(Block):
    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        attributes = ", ".join(
            f"{key}={value!r}" for key, value in self.__dict__.items()
        )
        return f"{class_name}({attributes})"

    def to_model(self):
        d = self.__dict__
        return internal.UnknownBlock.model_validate(d)

    @classmethod
    def from_model(cls, model: internal.UnknownBlock):
        d = model.model_dump()
        return cls(**d)


@dataclass(config=dataclass_config)
class TextWithInlineComments(Base):
    text: str

    _inline_comments: Optional[LList[internal.InlineComment]] = Field(
        default_factory=lambda: None, repr=False
    )


@dataclass(config=dataclass_config)
class Heading(Block):
    @classmethod
    def from_model(cls, model: internal.Heading):
        text = _internal_children_to_text(model.children)

        blocks = None
        if model.collapsed_children:
            blocks = [_lookup(b) for b in model.collapsed_children]

        if model.level == 1:
            return H1(text=text, collapsed_blocks=blocks)
        if model.level == 2:
            return H2(text=text, collapsed_blocks=blocks)
        if model.level == 3:
            return H3(text=text, collapsed_blocks=blocks)


@dataclass(config=dataclass_config)
class H1(Heading):
    text: TextLikeField = ""
    collapsed_blocks: Optional[LList["BlockTypes"]] = None

    def to_model(self):
        collapsed_children = self.collapsed_blocks
        if collapsed_children is not None:
            collapsed_children = [b.to_model() for b in collapsed_children]

        return internal.Heading(
            level=1,
            children=_text_to_internal_children(self.text),
            collapsed_children=collapsed_children,
        )


@dataclass(config=dataclass_config)
class H2(Heading):
    text: TextLikeField = ""
    collapsed_blocks: Optional[LList["BlockTypes"]] = None

    def to_model(self):
        collapsed_children = self.collapsed_blocks
        if collapsed_children is not None:
            collapsed_children = [b.to_model() for b in collapsed_children]

        return internal.Heading(
            level=2,
            children=_text_to_internal_children(self.text),
            collapsed_children=collapsed_children,
        )


@dataclass(config=dataclass_config)
class H3(Heading):
    text: TextLikeField = ""
    collapsed_blocks: Optional[LList["BlockTypes"]] = None

    def to_model(self):
        collapsed_children = self.collapsed_blocks
        if collapsed_children is not None:
            collapsed_children = [b.to_model() for b in collapsed_children]

        return internal.Heading(
            level=3,
            children=_text_to_internal_children(self.text),
            collapsed_children=collapsed_children,
        )


@dataclass(config=dataclass_config)
class Link(Base):
    text: Union[str, TextWithInlineComments]
    url: str

    _inline_comments: Optional[LList[internal.InlineComment]] = Field(
        default_factory=lambda: None, init=False, repr=False
    )


@dataclass(config=dataclass_config)
class InlineLatex(Base):
    text: str


@dataclass(config=dataclass_config)
class InlineCode(Base):
    text: str


@dataclass(config=dataclass_config)
class P(Block):
    text: TextLikeField = ""

    def to_model(self):
        children = _text_to_internal_children(self.text)
        return internal.Paragraph(children=children)

    @classmethod
    def from_model(cls, model: internal.Paragraph):
        pieces = _internal_children_to_text(model.children)
        return cls(text=pieces)


@dataclass(config=dataclass_config)
class ListItem(Base):
    @classmethod
    def from_model(cls, model: internal.ListItem):
        text = _internal_children_to_text(model.children)
        if model.checked is not None:
            return CheckedListItem(text=text, checked=model.checked)
        return text
        # if model.ordered is not None:
        #     return OrderedListItem(text=text)
        # return UnorderedListItem(text=text)


@dataclass(config=dataclass_config)
class CheckedListItem(Base):
    text: TextLikeField = ""
    checked: bool = False

    def to_model(self):
        return internal.ListItem(
            children=[
                internal.Paragraph(children=_text_to_internal_children(self.text))
            ],
            checked=self.checked,
        )


@dataclass(config=dataclass_config)
class OrderedListItem(Base):
    text: TextLikeField = ""

    def to_model(self):
        return internal.ListItem(
            children=[
                internal.Paragraph(children=_text_to_internal_children(self.text))
            ],
            ordered=True,
        )


@dataclass(config=dataclass_config)
class UnorderedListItem(Base):
    text: TextLikeField = ""

    def to_model(self):
        return internal.ListItem(
            children=[
                internal.Paragraph(children=_text_to_internal_children(self.text))
            ],
        )


@dataclass(config=dataclass_config)
class List(Block):
    @classmethod
    def from_model(cls, model: internal.List):
        if not model.children:
            return UnorderedList()

        item = model.children[0]
        items = [ListItem.from_model(x) for x in model.children]
        if item.checked is not None:
            return CheckedList(items=items)

        if item.ordered is not None:
            return OrderedList(items=items)

        # else unordered
        return UnorderedList(items=items)


@dataclass(config=dataclass_config)
class CheckedList(List):
    items: LList[CheckedListItem] = Field(default_factory=lambda: [CheckedListItem()])

    def to_model(self):
        items = [x.to_model() for x in self.items]
        return internal.List(children=items)


@dataclass(config=dataclass_config)
class OrderedList(List):
    items: LList[str] = Field(default_factory=lambda: [""])

    def to_model(self):
        children = [OrderedListItem(li).to_model() for li in self.items]
        return internal.List(children=children, ordered=True)


@dataclass(config=dataclass_config)
class UnorderedList(List):
    items: LList[str] = Field(default_factory=lambda: [""])

    def to_model(self):
        children = [UnorderedListItem(li).to_model() for li in self.items]
        return internal.List(children=children)


@dataclass(config=dataclass_config)
class BlockQuote(Block):
    text: TextLikeField = ""

    def to_model(self):
        return internal.BlockQuote(children=_text_to_internal_children(self.text))

    @classmethod
    def from_model(cls, model: internal.BlockQuote):
        return cls(text=_internal_children_to_text(model.children))


@dataclass(config=dataclass_config)
class CodeBlock(Block):
    code: TextLikeField = ""
    language: Optional[Language] = "python"

    def to_model(self):
        return internal.CodeBlock(
            children=[
                internal.CodeLine(
                    children=_text_to_internal_children(self.code),
                    language=self.language,
                )
            ],
            language=self.language,
        )

    @classmethod
    def from_model(cls, model: internal.CodeBlock):
        code = _internal_children_to_text(model.children[0].children)
        return cls(code=code, language=model.language)


@dataclass(config=dataclass_config)
class MarkdownBlock(Block):
    text: str = ""

    def to_model(self):
        return internal.MarkdownBlock(content=self.text)

    @classmethod
    def from_model(cls, model: internal.MarkdownBlock):
        return cls(text=model.content)


@dataclass(config=dataclass_config)
class LatexBlock(Block):
    text: str = ""

    def to_model(self):
        return internal.LatexBlock(content=self.text)

    @classmethod
    def from_model(cls, model: internal.LatexBlock):
        return cls(text=model.content)


@dataclass(config=dataclass_config)
class Image(Block):
    url: str = "https://raw.githubusercontent.com/wandb/assets/main/wandb-logo-yellow-dots-black-wb.svg"
    caption: TextLikeField = ""

    def to_model(self):
        has_caption = False
        children = _text_to_internal_children(self.caption)
        if children:
            has_caption = True

        return internal.Image(children=children, url=self.url, has_caption=has_caption)

    @classmethod
    def from_model(cls, model: internal.Image):
        caption = _internal_children_to_text(model.children)
        return cls(url=model.url, caption=caption)


@dataclass(config=dataclass_config)
class CalloutBlock(Block):
    text: TextLikeField = ""

    def to_model(self):
        return internal.CalloutBlock(
            children=[
                internal.CalloutLine(children=_text_to_internal_children(self.text))
            ]
        )

    @classmethod
    def from_model(cls, model: internal.CalloutBlock):
        text = _internal_children_to_text(model.children[0].children)
        return cls(text=text)


@dataclass(config=dataclass_config)
class HorizontalRule(Block):
    def to_model(self):
        return internal.HorizontalRule()

    @classmethod
    def from_model(cls, model: internal.HorizontalRule):
        return cls()


@dataclass(config=dataclass_config)
class Video(Block):
    url: str = "https://www.youtube.com/watch?v=krWjJcW80_A"

    def to_model(self):
        return internal.Video(url=self.url)

    @classmethod
    def from_model(cls, model: internal.Video):
        return cls(url=model.url)


@dataclass(config=dataclass_config)
class Spotify(Block):
    spotify_id: str

    def to_model(self):
        return internal.Spotify(spotify_id=self.spotify_id)

    @classmethod
    def from_model(cls, model: internal.Spotify):
        return cls(spotify_id=model.spotify_id)


@dataclass(config=dataclass_config)
class SoundCloud(Block):
    html: str

    def to_model(self):
        return internal.SoundCloud(html=self.html)

    @classmethod
    def from_model(cls, model: internal.SoundCloud):
        return cls(html=model.html)


@dataclass(config=dataclass_config)
class GalleryReport(Base):
    report_id: str


@dataclass(config=dataclass_config)
class GalleryURL(Base):
    url: str  # app accepts non-standard URL unfortunately
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


@dataclass(config=dataclass_config)
class Gallery(Block):
    items: LList[Union[GalleryReport, GalleryURL]] = Field(default_factory=list)

    def to_model(self):
        links = []
        for x in self.items:
            if isinstance(x, GalleryReport):
                link = internal.GalleryLinkReport(id=x.report_id)
            elif isinstance(x, GalleryURL):
                link = internal.GalleryLinkURL(
                    url=x.url,
                    title=x.title,
                    description=x.description,
                    image_url=x.image_url,
                )
            links.append(link)

        return internal.Gallery(links=links)

    @classmethod
    def from_model(cls, model: internal.Gallery):
        items = []
        if model.ids:
            items = [GalleryReport(x) for x in model.ids]
        elif model.links:
            for x in model.links:
                if isinstance(x, internal.GalleryLinkReport):
                    item = GalleryReport(report_id=x.id)
                elif isinstance(x, internal.GalleryLinkURL):
                    item = GalleryURL(
                        url=x.url,
                        title=x.title,
                        description=x.description,
                        image_url=x.image_url,
                    )
                items.append(item)

        return cls(items=items)


@dataclass(config=dataclass_config)
class OrderBy(Base):
    name: MetricType
    ascending: bool = False

    def to_model(self):
        return internal.SortKey(
            key=internal.SortKeyKey(name=_metric_to_backend(self.name)),
            ascending=self.ascending,
        )

    @classmethod
    def from_model(cls, model: internal.SortKey):
        return cls(
            name=_metric_to_frontend(model.key.name),
            ascending=model.ascending,
        )


@dataclass(config=dataclass_config)
class Runset(Base):
    entity: str = ""
    project: str = ""
    name: str = "Run set"
    query: str = ""
    filters: Optional[str] = ""
    groupby: LList[str] = Field(default_factory=list)
    order: LList[OrderBy] = Field(
        default_factory=lambda: [OrderBy("CreatedTimestamp", ascending=False)]
    )

    # this field does not get exported to model, but is used in PanelGrid
    custom_run_colors: Dict[Union[str, Tuple[MetricType, ...]], str] = Field(
        default_factory=dict
    )

    _id: str = Field(default_factory=internal._generate_name, init=False, repr=False)

    def to_model(self):
        project = None
        if self.entity or self.project:
            project = internal.Project(entity_name=self.entity, name=self.project)

        obj = internal.Runset(
            project=project,
            name=self.name,
            filters=expr_parsing.expr_to_filters(self.filters),
            grouping=[
                internal.Key(name=expr_parsing.to_backend_name(g)) for g in self.groupby
            ],
            sort=internal.Sort(keys=[o.to_model() for o in self.order]),
        )
        obj.id = self._id
        return obj

    @classmethod
    def from_model(cls, model: internal.Runset):
        entity = ""
        project = ""

        p = model.project
        if p is not None:
            if p.entity_name:
                entity = p.entity_name
            if p.name:
                project = p.name

        obj = cls(
            entity=entity,
            project=project,
            name=model.name,
            filters=expr_parsing.filters_to_expr(model.filters),
            groupby=[expr_parsing.to_frontend_name(k.name) for k in model.grouping],
            order=[OrderBy.from_model(s) for s in model.sort.keys],
        )
        obj._id = model.id
        return obj


@dataclass(config=dataclass_config)
class Panel(Base):
    id: str = Field(default_factory=internal._generate_name, kw_only=True)
    layout: Layout = Field(default_factory=Layout, kw_only=True)

    _ref: Optional[internal.Ref] = Field(
        default_factory=lambda: None, init=False, repr=False
    )


@dataclass(config=dataclass_config)
class PanelGrid(Block):
    runsets: LList["Runset"] = Field(default_factory=lambda: [Runset()])
    panels: LList["PanelTypes"] = Field(default_factory=list)
    active_runset: int = 0
    custom_run_colors: Dict[Union[RunId, RunsetGroup], str] = Field(
        default_factory=dict
    )

    _ref: Optional[internal.Ref] = Field(
        default_factory=lambda: None, init=False, repr=False
    )
    _open_viz: bool = Field(default_factory=lambda: True, init=False, repr=False)
    _panel_bank_sections: LList[dict] = Field(
        default_factory=list, init=False, repr=False
    )
    _panel_grid_metadata_ref: Optional[internal.Ref] = Field(
        default_factory=lambda: None, init=False, repr=False
    )

    def to_model(self):
        return internal.PanelGrid(
            metadata=internal.PanelGridMetadata(
                run_sets=[rs.to_model() for rs in self.runsets],
                panel_bank_section_config=internal.PanelBankSectionConfig(
                    panels=[p.to_model() for p in self.panels],
                ),
                panels=internal.PanelGridMetadataPanels(
                    ref=self._panel_grid_metadata_ref,
                    panel_bank_config=internal.PanelBankConfig(),
                    open_viz=self._open_viz,
                ),
                custom_run_colors=_to_color_dict(self.custom_run_colors, self.runsets),
            )
        )

    @classmethod
    def from_model(cls, model: internal.PanelGrid):
        runsets = [Runset.from_model(rs) for rs in model.metadata.run_sets]
        obj = cls(
            runsets=runsets,
            panels=[
                _lookup_panel(p)
                for p in model.metadata.panel_bank_section_config.panels
            ],
            active_runset=model.metadata.open_run_set,
            custom_run_colors=_from_color_dict(
                model.metadata.custom_run_colors, runsets
            ),
            # _panel_bank_sections=model.metadata.panel_bank_config.sections,
        )
        obj._open_viz = model.metadata.open_viz
        obj._ref = model.metadata.panels.ref
        return obj

    @validator("panels")
    def _resolve_collisions(cls, v):  # noqa: N805
        v2 = _resolve_collisions(v)
        return v2

    @validator("runsets")
    def _validate_list_not_empty(cls, v):  # noqa: N805
        if len(v) < 1:
            raise ValueError("must have at least one runset")
        return v


@dataclass(config=dataclass_config)
class TableOfContents(Block):
    def to_model(self):
        return internal.TableOfContents()

    @classmethod
    def from_model(cls, model: internal.TableOfContents):
        return cls()


@dataclass(config=dataclass_config)
class Twitter(Block):
    html: str

    def to_model(self):
        return internal.Twitter(html=self.html)

    @classmethod
    def from_model(cls, model: internal.Twitter):
        return cls(html=model.html)


@dataclass(config=dataclass_config)
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
    UnorderedList,
    OrderedList,
    CheckedList,
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
]


block_mapping = {
    internal.Paragraph: P,
    internal.CalloutBlock: CalloutBlock,
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
    internal.BlockQuote: BlockQuote,
    internal.Spotify: Spotify,
    internal.Twitter: Twitter,
    internal.SoundCloud: SoundCloud,
    internal.UnknownBlock: UnknownBlock,
}


@dataclass(config=dataclass_config)
class GradientPoint(Base):
    color: str
    offset: float = Field(0, ge=0, le=100)

    @validator("color")
    def validate_color(cls, v):  # noqa: N805
        if not internal.is_valid_color(v):
            raise ValueError("invalid color, value should be hex, rgb, or rgba")
        return v

    def to_model(self):
        return internal.GradientPoint(color=self.color, offset=self.offset)

    @classmethod
    def from_model(cls, model: internal.GradientPoint):
        return cls(color=model.color, offset=model.offset)


@dataclass(config=dataclass_config)
class LinePlot(Panel):
    title: Optional[str] = None
    x: Optional[MetricType] = "Step"
    y: LList[MetricType] = Field(default_factory=list)
    range_x: Range = Field(default_factory=lambda: (None, None))
    range_y: Range = Field(default_factory=lambda: (None, None))
    log_x: Optional[bool] = None
    log_y: Optional[bool] = None
    title_x: Optional[str] = None
    title_y: Optional[str] = None
    ignore_outliers: Optional[bool] = None
    groupby: Optional[str] = None
    groupby_aggfunc: Optional[GroupAgg] = None
    groupby_rangefunc: Optional[GroupArea] = None
    smoothing_factor: Optional[float] = None
    smoothing_type: Optional[SmoothingType] = None
    smoothing_show_original: Optional[bool] = None
    max_runs_to_show: Optional[int] = None
    custom_expressions: Optional[LList[str]] = None
    plot_type: Optional[LinePlotStyle] = None
    font_size: Optional[FontSize] = None
    legend_position: Optional[LegendPosition] = None
    legend_template: Optional[str] = None
    aggregate: Optional[bool] = None
    xaxis_expression: Optional[str] = None

    def to_model(self):
        obj = internal.LinePlot(
            config=internal.LinePlotConfig(
                chart_title=self.title,
                x_axis=_metric_to_backend(self.x),
                metrics=[_metric_to_backend(name) for name in _listify(self.y)],
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
            id=self.id,
            layout=self.layout.to_model(),
        )
        obj.ref = self._ref
        return obj

    @classmethod
    def from_model(cls, model: internal.LinePlot):
        obj = cls(
            title=model.config.chart_title,
            x=_metric_to_frontend(model.config.x_axis),
            y=[_metric_to_frontend(name) for name in model.config.metrics],
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
            layout=Layout.from_model(model.layout),
            id=model.id,
        )
        obj._ref = model.ref
        return obj


@dataclass(config=dataclass_config)
class ScatterPlot(Panel):
    title: Optional[str] = None
    x: Optional[MetricType] = None
    y: Optional[MetricType] = None
    z: Optional[MetricType] = None
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
    gradient: Optional[LList[GradientPoint]] = None
    font_size: Optional[FontSize] = None
    regression: Optional[bool] = None

    def to_model(self):
        custom_gradient = self.gradient
        if custom_gradient is not None:
            custom_gradient = [cgp.to_model() for cgp in self.gradient]

        obj = internal.ScatterPlot(
            config=internal.ScatterPlotConfig(
                chart_title=self.title,
                x_axis=_metric_to_backend(self.x),
                y_axis=_metric_to_backend(self.y),
                z_axis=_metric_to_backend(self.z),
                x_axis_min=self.range_x[0],
                x_axis_max=self.range_x[1],
                y_axis_min=self.range_y[0],
                y_axis_max=self.range_y[1],
                z_axis_min=self.range_z[0],
                z_axis_max=self.range_z[1],
                x_axis_log_scale=self.log_x,
                y_axis_log_scale=self.log_y,
                z_axis_log_scale=self.log_z,
                show_min_y_axis_line=self.running_ymin,
                show_max_y_axis_line=self.running_ymax,
                show_avg_y_axis_line=self.running_ymean,
                legend_template=self.legend_template,
                custom_gradient=custom_gradient,
                font_size=self.font_size,
                show_linear_regression=self.regression,
            ),
            layout=self.layout.to_model(),
            id=self.id,
        )
        obj.ref = self._ref
        return obj

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        gradient = model.config.custom_gradient
        if gradient is not None:
            gradient = [GradientPoint.from_model(cgp) for cgp in gradient]

        obj = cls(
            title=model.config.chart_title,
            x=_metric_to_frontend(model.config.x_axis),
            y=_metric_to_frontend(model.config.y_axis),
            z=_metric_to_frontend(model.config.z_axis),
            range_x=(model.config.x_axis_min, model.config.x_axis_max),
            range_y=(model.config.y_axis_min, model.config.y_axis_max),
            range_z=(model.config.z_axis_min, model.config.z_axis_max),
            log_x=model.config.x_axis_log_scale,
            log_y=model.config.y_axis_log_scale,
            log_z=model.config.z_axis_log_scale,
            running_ymin=model.config.show_min_y_axis_line,
            running_ymax=model.config.show_max_y_axis_line,
            running_ymean=model.config.show_avg_y_axis_line,
            legend_template=model.config.legend_template,
            gradient=gradient,
            font_size=model.config.font_size,
            regression=model.config.show_linear_regression,
            layout=Layout.from_model(model.layout),
            id=model.id,
        )
        obj._ref = model.ref
        return obj


@dataclass(config=dataclass_config)
class BarPlot(Panel):
    title: Optional[str] = None
    metrics: LList[MetricType] = Field(default_factory=list)
    orientation: Literal["v", "h"] = "h"
    range_x: Range = Field(default_factory=lambda: (None, None))
    title_x: Optional[str] = None
    title_y: Optional[str] = None
    groupby: Optional[str] = None
    groupby_aggfunc: Optional[GroupAgg] = None
    groupby_rangefunc: Optional[GroupArea] = None
    max_runs_to_show: Optional[int] = None
    max_bars_to_show: Optional[int] = None
    custom_expressions: Optional[LList[str]] = None
    legend_template: Optional[str] = None
    font_size: Optional[FontSize] = None
    line_titles: Optional[dict] = None
    line_colors: Optional[dict] = None

    def to_model(self):
        obj = internal.BarPlot(
            config=internal.BarPlotConfig(
                chart_title=self.title,
                metrics=[_metric_to_backend(name) for name in _listify(self.metrics)],
                vertical=self.orientation == "v",
                x_axis_min=self.range_x[0],
                x_axis_max=self.range_x[1],
                x_axis_title=self.title_x,
                y_axis_title=self.title_y,
                group_by=self.groupby,
                group_agg=self.groupby_aggfunc,
                group_area=self.groupby_rangefunc,
                limit=self.max_runs_to_show,
                bar_limit=self.max_bars_to_show,
                expressions=self.custom_expressions,
                legend_template=self.legend_template,
                font_size=self.font_size,
                override_series_titles=self.line_titles,
                override_colors=self.line_colors,
            ),
            layout=self.layout.to_model(),
            id=self.id,
        )
        obj.ref = self._ref
        return obj

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        obj = cls(
            title=model.config.chart_title,
            metrics=[_metric_to_frontend(name) for name in model.config.metrics],
            orientation="v" if model.config.vertical else "h",
            range_x=(model.config.x_axis_min, model.config.x_axis_max),
            title_x=model.config.x_axis_title,
            title_y=model.config.y_axis_title,
            groupby=model.config.group_by,
            groupby_aggfunc=model.config.group_agg,
            groupby_rangefunc=model.config.group_area,
            max_runs_to_show=model.config.limit,
            max_bars_to_show=model.config.bar_limit,
            custom_expressions=model.config.expressions,
            legend_template=model.config.legend_template,
            font_size=model.config.font_size,
            line_titles=model.config.override_series_titles,
            line_colors=model.config.override_colors,
            layout=Layout.from_model(model.layout),
            id=model.id,
        )
        obj._ref = model.ref
        return obj


@dataclass(config=dataclass_config)
class ScalarChart(Panel):
    title: Optional[str] = None
    metric: MetricType = ""
    groupby_aggfunc: Optional[GroupAgg] = None
    groupby_rangefunc: Optional[GroupArea] = None
    custom_expressions: Optional[LList[str]] = None
    legend_template: Optional[str] = None
    font_size: Optional[FontSize] = None

    def to_model(self):
        obj = internal.ScalarChart(
            config=internal.ScalarChartConfig(
                chart_title=self.title,
                metrics=[_metric_to_backend(self.metric)],
                group_agg=self.groupby_aggfunc,
                group_area=self.groupby_rangefunc,
                expressions=self.custom_expressions,
                legend_template=self.legend_template,
                font_size=self.font_size,
            ),
            layout=self.layout.to_model(),
            id=self.id,
        )
        obj.ref = self._ref
        return obj

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        obj = cls(
            title=model.config.chart_title,
            metric=_metric_to_frontend(model.config.metrics[0]),
            groupby_aggfunc=model.config.group_agg,
            groupby_rangefunc=model.config.group_area,
            custom_expressions=model.config.expressions,
            legend_template=model.config.legend_template,
            font_size=model.config.font_size,
            layout=Layout.from_model(model.layout),
            id=model.id,
        )
        obj._ref = model.ref
        return obj


@dataclass(config=dataclass_config)
class CodeComparer(Panel):
    diff: CodeCompareDiff = "split"

    def to_model(self):
        obj = internal.CodeComparer(
            config=internal.CodeComparerConfig(diff=self.diff),
            layout=self.layout.to_model(),
            id=self.id,
        )
        obj.ref = self._ref
        return obj

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        obj = cls(
            diff=model.config.diff,
            layout=Layout.from_model(model.layout),
            id=model.id,
        )
        obj._ref = model.ref
        return obj


@dataclass(config=dataclass_config)
class ParallelCoordinatesPlotColumn(Base):
    metric: ParallelCoordinatesMetric
    display_name: Optional[str] = None
    inverted: Optional[bool] = None
    log: Optional[bool] = None

    _ref: Optional[internal.Ref] = Field(
        default_factory=lambda: None, init=False, repr=False
    )

    def to_model(self):
        obj = internal.Column(
            accessor=_metric_to_backend_pc(self.metric),
            display_name=self.display_name,
            inverted=self.inverted,
            log=self.log,
        )
        obj.ref = self._ref
        return obj

    @classmethod
    def from_model(cls, model: internal.Column):
        obj = cls(
            metric=_metric_to_frontend_pc(model.accessor),
            display_name=model.display_name,
            inverted=model.inverted,
            log=model.log,
        )
        obj._ref = model.ref
        return obj


@dataclass(config=dataclass_config)
class ParallelCoordinatesPlot(Panel):
    columns: LList[ParallelCoordinatesPlotColumn] = Field(default_factory=list)
    title: Optional[str] = None
    gradient: Optional[LList[GradientPoint]] = None
    font_size: Optional[FontSize] = None

    def to_model(self):
        gradient = self.gradient
        if gradient is not None:
            gradient = [x.to_model() for x in self.gradient]

        obj = internal.ParallelCoordinatesPlot(
            config=internal.ParallelCoordinatesPlotConfig(
                chart_title=self.title,
                columns=[c.to_model() for c in self.columns],
                custom_gradient=gradient,
                font_size=self.font_size,
            ),
            layout=self.layout.to_model(),
            id=self.id,
        )
        obj.ref = self._ref
        return obj

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        gradient = model.config.custom_gradient
        if gradient is not None:
            gradient = [GradientPoint.from_model(x) for x in gradient]

        obj = cls(
            columns=[
                ParallelCoordinatesPlotColumn.from_model(c)
                for c in model.config.columns
            ],
            title=model.config.chart_title,
            gradient=gradient,
            font_size=model.config.font_size,
            layout=Layout.from_model(model.layout),
            id=model.id,
        )
        obj._ref = model.ref
        return obj


@dataclass(config=dataclass_config)
class ParameterImportancePlot(Panel):
    with_respect_to: str = ""

    def to_model(self):
        obj = internal.ParameterImportancePlot(
            config=internal.ParameterImportancePlotConfig(
                target_key=self.with_respect_to
            ),
            layout=self.layout.to_model(),
            id=self.id,
        )
        obj.ref = self._ref
        return obj

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        obj = cls(
            with_respect_to=model.config.target_key,
            layout=Layout.from_model(model.layout),
            id=model.id,
        )
        obj._ref = model.ref
        return obj


@dataclass(config=dataclass_config)
class RunComparer(Panel):
    diff_only: Optional[Literal["split", True]] = None

    def to_model(self):
        obj = internal.RunComparer(
            config=internal.RunComparerConfig(diff_only=self.diff_only),
            layout=self.layout.to_model(),
            id=self.id,
        )
        obj.ref = self._ref
        return obj

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        obj = cls(
            diff_only=model.config.diff_only,
            layout=Layout.from_model(model.layout),
            id=model.id,
        )
        obj._ref = model.ref
        return obj


@dataclass(config=dataclass_config)
class MediaBrowser(Panel):
    num_columns: Optional[int] = None
    media_keys: LList[str] = Field(default_factory=list)

    def to_model(self):
        obj = internal.MediaBrowser(
            config=internal.MediaBrowserConfig(
                column_count=self.num_columns,
                media_keys=self.media_keys,
            ),
            layout=self.layout.to_model(),
            id=self.id,
        )
        obj.ref = self._ref
        return obj

    @classmethod
    def from_model(cls, model: internal.MediaBrowser):
        obj = cls(
            num_columns=model.config.column_count,
            media_keys=model.config.media_keys,
            layout=Layout.from_model(model.layout),
            id=model.id,
        )
        obj._ref = model.ref
        return obj


@dataclass(config=dataclass_config)
class MarkdownPanel(Panel):
    markdown: str = ""

    def to_model(self):
        obj = internal.MarkdownPanel(
            config=internal.MarkdownPanelConfig(value=self.markdown),
            layout=self.layout.to_model(),
            id=self.id,
        )
        obj.ref = self._ref
        return obj

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        obj = cls(
            markdown=model.config.value,
            layout=Layout.from_model(model.layout),
            id=model.id,
        )
        obj._ref = model.ref
        return obj


# @dataclass(config=dataclass_config)
# class ConfusionMatrix(Panel):
#     def to_model(self):
#         ...

#     @classmethod
#     def from_model(cls, model: internal.ConfusionMatrix):
#         ...


# @dataclass(config=dataclass_config)
# class DataFrames(Panel):
#     def to_model(self):
#         ...

#     @classmethod
#     def from_model(cls, model: internal.ScatterPlot):
#         ...


# @dataclass(config=dataclass_config)
# class MultiRunTable(Panel):
#     def to_model(self):
#         ...

#     @classmethod
#     def from_model(cls, model: internal.ScatterPlot):
#         ...


# @dataclass(config=dataclass_config)
# class Vega(Panel):
#     def to_model(self):
#         ...

#     @classmethod
#     def from_model(cls, model: internal.ScatterPlot):
#         ...


# @dataclass(config=dataclass_config)
# class Vega3(Panel):
#     def to_model(self):
#         ...

#     @classmethod
#     def from_model(cls, model: internal.ScatterPlot):
#         ...


@dataclass(config=dataclass_config)
class CustomChart(Panel):
    query: dict = Field(default_factory=dict)
    chart_name: str = Field(default_factory=dict)
    chart_fields: dict = Field(default_factory=dict)
    chart_strings: dict = Field(default_factory=dict)

    @classmethod
    def from_table(
        cls, table_name: str, chart_fields: dict = None, chart_strings: dict = None
    ):
        return cls(
            query={"summaryTable": {"tableKey": table_name}},
            chart_fields=chart_fields,
            chart_strings=chart_strings,
        )

    def to_model(self):
        obj = internal.Vega2(
            config=internal.Vega2Config(
                # user_query=internal.UserQuery(
                #     query_fields=[
                #         internal.QueryField(
                #             args=...,
                #             fields=...,
                #             name=...,
                #         )
                #     ]
                # )
            ),
            layout=self.layout.to_model(),
        )
        obj.ref = self._ref
        # obj.id=self.id,
        return obj

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        obj = cls(
            # query=model.config.user_query.query_fields,
            # chart_name=model.config.panel_def_id,
            # chart_fields=model.config.field_settings,
            # chart_strings=model.config.string_settings,
            layout=Layout.from_model(model.layout),
        )
        obj._ref = model.ref
        return obj


@dataclass(config=ConfigDict(validate_assignment=True, extra="forbid", slots=True))
class UnknownPanel(Base):
    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        attributes = ", ".join(
            f"{key}={value!r}" for key, value in self.__dict__.items()
        )
        return f"{class_name}({attributes})"

    def to_model(self):
        d = self.__dict__
        print(d)
        return internal.UnknownPanel.model_validate(d)

    @classmethod
    def from_model(cls, model: internal.UnknownPanel):
        d = model.model_dump()
        return cls(**d)


@dataclass(config=ConfigDict(validate_assignment=True, extra="forbid", slots=True))
class WeavePanel(Panel):
    config: dict = Field(default_factory=dict)

    def to_model(self):
        return internal.WeavePanel(config=self.config)

    @classmethod
    def from_model(cls, model: internal.WeavePanel):
        return cls(config=model.config)


@dataclass(config=dataclass_config)
class Report(Base):
    project: str
    entity: str = Field(default_factory=lambda: _get_api().default_entity)
    title: str = Field("Untitled Report", max_length=128)
    width: ReportWidth = "readable"
    description: str = ""
    blocks: LList[BlockTypes] = Field(default_factory=list)

    id: str = Field(default_factory=lambda: "", init=False, repr=False)

    _discussion_threads: list = Field(default_factory=list, init=False, repr=False)
    _ref: dict = Field(default_factory=dict, init=False, repr=False)
    _panel_settings: dict = Field(default_factory=dict, init=False, repr=False)
    _authors: LList[dict] = Field(default_factory=list, init=False, repr=False)
    _created_at: Optional[datetime] = Field(
        default_factory=lambda: None, init=False, repr=False
    )
    _updated_at: Optional[datetime] = Field(
        default_factory=lambda: None, init=False, repr=False
    )

    def to_model(self):
        blocks = self.blocks
        if len(blocks) > 0 and blocks[0] != P():
            blocks = [P()] + blocks

        if len(blocks) > 0 and blocks[-1] != P():
            blocks = blocks + [P()]

        if not blocks:
            blocks = [P(), P()]

        return internal.ReportViewspec(
            display_name=self.title,
            description=self.description,
            project=internal.Project(name=self.project, entity_name=self.entity),
            id=self.id,
            created_at=self._created_at,
            updated_at=self._updated_at,
            spec=internal.Spec(
                panel_settings=self._panel_settings,
                blocks=[b.to_model() for b in blocks],
                width=self.width,
                authors=self._authors,
                discussion_threads=self._discussion_threads,
                ref=self._ref,
            ),
        )

    @classmethod
    def from_model(cls, model: internal.ReportViewspec):
        blocks = model.spec.blocks

        if blocks[0] == internal.Paragraph():
            blocks = blocks[1:]

        if blocks[-1] == internal.Paragraph():
            blocks = blocks[:-1]

        return cls(
            title=model.display_name,
            description=model.description,
            entity=model.project.entity_name,
            project=model.project.name,
            id=model.id,
            blocks=[_lookup(b) for b in blocks],
            _discussion_threads=model.spec.discussion_threads,
            _panel_settings=model.spec.panel_settings,
            _ref=model.spec.ref,
            _authors=model.spec.authors,
            _created_at=model.created_at,
            _updated_at=model.updated_at,
        )

    @property
    def url(self):
        if self.id == "":
            raise AttributeError("save report or explicitly pass `id` to get a url")

        base = urlparse(_get_api().client.app_url)

        title = self.title.replace(" ", "-")

        scheme = base.scheme
        netloc = base.netloc
        path = os.path.join(self.entity, self.project, "reports", f"{title}--{self.id}")
        params = ""
        query = ""
        fragment = ""

        return urlunparse((scheme, netloc, path, params, query, fragment))

    def save(self, draft: bool = False, clone: bool = False):
        model = self.to_model()

        # create project if not exists
        projects = _get_api().projects(self.entity)
        is_new_project = True
        for p in projects:
            if p.name == self.project:
                is_new_project = False
                break

        if is_new_project:
            _get_api().create_project(self.project, self.entity)

        r = _get_api().client.execute(
            gql.upsert_view,
            variable_values={
                "id": None if clone or not model.id else model.id,
                "name": internal._generate_name()
                if clone or not model.name
                else model.name,
                "entityName": model.project.entity_name,
                "projectName": model.project.name,
                "description": model.description,
                "displayName": model.display_name,
                "type": "runs/draft" if draft else "runs",
                "spec": model.spec.model_dump_json(by_alias=True, exclude_none=True),
            },
        )

        viewspec = r["upsertView"]["view"]
        new_model = internal.ReportViewspec.model_validate(viewspec)
        self.id = new_model.id

        wandb.termlog(f"Saved report to: {self.url}")
        return self

    @classmethod
    def from_url(cls, url, *, as_model: bool = False):
        vs = _url_to_viewspec(url)
        model = internal.ReportViewspec.model_validate(vs)
        if as_model:
            return model
        return cls.from_model(model)

    def to_html(self, height: int = 1024, hidden: bool = False) -> str:
        """Generate HTML containing an iframe displaying this report."""
        try:
            url = self.url + "?jupyter=true"
            style = f"border:none;width:100%;height:{height}px;"
            prefix = ""
            if hidden:
                style += "display:none;"
                prefix = wandb.sdk.lib.ipython.toggle_button("report")
            return prefix + f"<iframe src={url!r} style={style!r}></iframe>"
        except AttributeError:
            wandb.termlog("HTML repr will be available after you save the report!")

    def _repr_html_(self) -> str:
        return self.to_html()


def _get_api():
    try:
        return wandb.Api()
    except wandb.errors.UsageError as e:
        raise Exception("not logged in to W&B, try `wandb login --relogin`") from e


def _url_to_viewspec(url):
    report_id = _url_to_report_id(url)
    r = _get_api().client.execute(
        gql.view_report, variable_values={"reportId": report_id}
    )
    viewspec = r["view"]
    return viewspec


def _url_to_report_id(url):
    parse_result = urlparse(url)
    path = parse_result.path

    _, entity, project, _, name = path.split("/")
    title, report_id = name.split("--")

    return report_id


def _lookup(block):
    cls = block_mapping.get(block.__class__, UnknownBlock)
    return cls.from_model(block)


def _should_show_attr(k, v):
    if k.startswith("_"):
        return False
    if k == "id":
        return False
    if v is None:
        return False
    if isinstance(v, Iterable) and not isinstance(v, (str, bytes, bytearray)):
        return not all(x is None for x in v)
    # ignore the default layout
    if isinstance(v, Layout) and v.x == 0 and v.y == 0 and v.w == 8 and v.h == 6:
        return False
    return True


def _listify(x):
    if isinstance(x, Iterable):
        return list(x)
    return [x]


def _lookup_panel(panel):
    cls = panel_mapping.get(panel.__class__, UnknownPanel)
    return cls.from_model(panel)


def _load_spec_from_url(url, as_model=False):
    import json

    vs = _url_to_viewspec(url)
    spec = vs["spec"]
    if as_model:
        return internal.Spec.model_validate_json(spec)
    return json.loads(spec)


panel_mapping = {
    internal.LinePlot: LinePlot,
    internal.ScatterPlot: ScatterPlot,
    internal.BarPlot: BarPlot,
    internal.ScalarChart: ScalarChart,
    internal.CodeComparer: CodeComparer,
    internal.ParallelCoordinatesPlot: ParallelCoordinatesPlot,
    internal.ParameterImportancePlot: ParameterImportancePlot,
    internal.RunComparer: RunComparer,
    internal.Vega2: CustomChart,
    internal.WeavePanel: WeavePanel,
    internal.MediaBrowser: MediaBrowser,
    internal.MarkdownPanel: MarkdownPanel,
}

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
    CustomChart,
    WeavePanel,
    UnknownPanel,
]


def _text_to_internal_children(text_field):
    text = text_field
    if text == []:
        text = ""
    # if isinstance(text, str):
    if not isinstance(text, list):
        text = [text]

    texts = []
    for x in text:
        t = None
        if isinstance(x, str):
            t = internal.Text(text=x)
        elif isinstance(x, TextWithInlineComments):
            t = internal.Text(text=x.text, inline_comments=x._inline_comments)
        elif isinstance(x, Link):
            txt = x.text
            if isinstance(txt, str):
                children = [internal.Text(text=txt)]
            elif isinstance(txt, TextWithInlineComments):
                children = [
                    internal.Text(text=txt.text, inline_comments=txt._inline_comments)
                ]
            t = internal.InlineLink(url=x.url, children=children)
        elif isinstance(x, InlineLatex):
            t = internal.InlineLatex(content=x.text)
        elif isinstance(x, InlineCode):
            t = internal.Text(text=x.text, inline_code=True)
        texts.append(t)
    if not all(isinstance(x, str) for x in texts):
        pass
    return texts


def _generate_thing(x):
    if isinstance(x, internal.Paragraph):
        return _internal_children_to_text(x.children)
    elif isinstance(x, internal.Text):
        if x.inline_code:
            return InlineCode(x.text)
        elif x.inline_comments:
            return TextWithInlineComments(
                text=x.text, _inline_comments=x.inline_comments
            )
        return x.text
    elif isinstance(x, internal.InlineLink):
        text_obj = x.children[0]
        if text_obj.inline_comments:
            text = TextWithInlineComments(
                text=text_obj.text, _inline_comments=text_obj.inline_comments
            )
        else:
            text = text_obj.text
        return Link(url=x.url, text=text)
    elif isinstance(x, internal.InlineLatex):
        return InlineLatex(text=x.content)


def _internal_children_to_text(children):
    pieces = []
    for x in children:
        t = _generate_thing(x)
        if isinstance(t, list):
            for x in t:
                pieces.append(x)
        else:
            pieces.append(t)

    if not pieces:
        return ""

    if len(pieces) == 1 and isinstance(pieces[0], str):
        return pieces[0]

    if len(pieces) == 3 and pieces[0] == "" and pieces[-1] == "":
        return pieces[1]

    if len(pieces) >= 3 and pieces[0] == "" and pieces[-1] == "":
        return pieces[1:-1]

    if all(x == "" for x in pieces):
        return ""

    return pieces


def _resolve_collisions(panels: LList[Panel], x_max: int = 24):
    for i, p1 in enumerate(panels):
        for p2 in panels[i + 1 :]:
            l1, l2 = p1.layout, p2.layout

            if _collides(p1, p2):
                x = l1.x + l1.w - l2.x
                y = l1.y + l1.h - l2.y

                if l2.x + l2.w + x <= x_max:
                    l2.x += x

                else:
                    l2.y += y
                    l2.x = 0
    return panels


def _collides(p1: Panel, p2: Panel) -> bool:
    l1, l2 = p1.layout, p2.layout

    if (
        (p1.id == p2.id)
        or (l1.x + l1.w <= l2.x)
        or (l1.x >= l2.w + l2.x)
        or (l1.y + l1.h <= l2.y)
        or (l1.y >= l2.y + l2.h)
    ):
        return False

    return True


def _metric_to_backend(x: Optional[MetricType]):
    if x is None:
        return x
    if isinstance(x, str):  # Same as Metric
        return expr_parsing.to_backend_name(x)
    if isinstance(x, Metric):
        name = x.name
        return expr_parsing.to_backend_name(name)
    if isinstance(x, Config):
        name, *rest = x.name.split(".")
        rest = "." + ".".join(rest) if rest else ""
        return f"config.{name}.value{rest}"
    if isinstance(x, SummaryMetric):
        name = x.name
        return f"summary_metrics.{name}"
    raise Exception("Unexpected metric type")


def _metric_to_frontend(x: str):
    if x is None:
        return x
    if x.startswith("config.") and ".value" in x:
        name = x.replace("config.", "").replace(".value", "")
        return Config(name)
    if x.startswith("summary_metrics."):
        name = x.replace("summary_metrics.", "")
        return SummaryMetric(name)

    name = expr_parsing.to_frontend_name(x)
    return Metric(name)


def _metric_to_backend_pc(x: Optional[ParallelCoordinatesMetric]):
    if x is None:
        return x
    if isinstance(x, str):  # Same as SummaryMetric
        name = x
        return f"summary:{name}"
    if isinstance(x, Config):
        name = x.name
        return f"c::{name}"
    if isinstance(x, SummaryMetric):
        name = x.name
        return f"summary:{name}"
    raise Exception("Unexpected metric type")


def _metric_to_frontend_pc(x: str):
    if x is None:
        return x
    if x.startswith("c::"):
        name = x.replace("c::", "")
        return Config(name)
    if x.startswith("summary:"):
        name = x.replace("summary:", "")
        return SummaryMetric(name)

    name = expr_parsing.to_frontend_name(x)
    return Metric(name)


def _metric_to_backend_panel_grid(x: Optional[MetricType]):
    if isinstance(x, str):
        name, *rest = x.split(".")
        rest = "." + ".".join(rest) if rest else ""
        return f"config:{name}.value{rest}"
    return _metric_to_backend(x)


def _metric_to_frontend_panel_grid(x: str):
    if x.startswith("config:") and ".value" in x:
        name = x.replace("config:", "").replace(".value", "")
        return Config(name)
    return _metric_to_frontend(x)


def _get_rs_by_name(runsets, name):
    for rs in runsets:
        if rs.name == name:
            return rs


def _get_rs_by_id(runsets, id):
    for rs in runsets:
        if rs._id == id:
            return rs


def _to_color_dict(custom_run_colors, runsets):
    d = {}
    for k, v in custom_run_colors.items():
        if isinstance(k, RunsetGroup):
            rs = _get_rs_by_name(runsets, k.runset_name)
            if not rs:
                continue
            id = rs._id
            kvs = []
            for keys in k.keys:
                kk = _metric_to_backend_panel_grid(keys.key)
                vv = keys.value
                kv = f"{kk}:{vv}"
                kvs.append(kv)
            linked = "-".join(kvs)
            key = f"{id}-{linked}"
        else:
            key = k
        d[key] = v

    return d


def _from_color_dict(d, runsets):
    d2 = {}
    for k, v in d.items():
        id, *backend_parts = k.split("-")

        if backend_parts:
            groups = []
            for part in backend_parts:
                key, value = part.rsplit(":", 1)
                kkey = _metric_to_frontend_panel_grid(key)
                group = RunsetGroupKey(kkey, value)
                groups.append(group)
            rs = _get_rs_by_id(runsets, id)
            rg = RunsetGroup(runset_name=rs.name, keys=groups)
            new_key = rg
        else:
            new_key = k
        d2[new_key] = v
    return d2
