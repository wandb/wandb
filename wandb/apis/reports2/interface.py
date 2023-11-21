import os
import re
from dataclasses import fields, is_dataclass
from typing import Iterable, Literal, Optional, Union
from urllib.parse import urlparse, urlunparse

from pydantic import AnyUrl, ConfigDict, Field, validator
from pydantic.dataclasses import dataclass

import wandb

from . import gql, internal
from .internal import (
    CodeCompareDiff,
    FontSize,
    GroupAgg,
    GroupArea,
    Language,
    LegendPosition,
    LinePlotStyle,
    Range,
    ReportEntity,
    ReportProject,
    SmoothingType,
)

_api = wandb.Api()
DEFAULT_ENTITY = _api.default_entity

dataclass_config = ConfigDict(validate_assignment=True, extra="forbid", slots=True)
dataclass_settings = {"config": dataclass_config, "repr": False}


def _format_attr(name, value, indent, max_line_length, is_list_item=False):
    formatted_value = repr(value)
    if len(formatted_value) <= max_line_length:
        prefix = f"{indent}{name}=" if not is_list_item else indent
        return f"{prefix}{formatted_value}"

    if isinstance(value, list) and all(is_dataclass(item) for item in value):
        nested_indent = indent + "    "
        nested_reprs = [
            nested_indent + repr(item).replace("\n", "\n" + nested_indent)
            for item in value
        ]
        return f"{indent}{name}=[\n" + ",\n".join(nested_reprs) + "\n" + indent + "]"
    else:
        prefix = f"{indent}{name}=" if not is_list_item else indent
        return f"{prefix}{formatted_value}"


@dataclass(**dataclass_settings)
class Base:
    def __repr__(self):
        max_line_length = 80
        indent = "    "
        field_strings = []
        single_line = self.__class__.__name__ + "("

        for f in fields(self):
            value = getattr(self, f.name)
            if _should_show_attr(f.name, value):
                field_str = _format_attr(f.name, value, indent, max_line_length)
                single_line += field_str[len(indent) :] + ", "

                if len(single_line) > max_line_length:
                    field_strings = [
                        _format_attr(
                            f.name, getattr(self, f.name), indent, max_line_length
                        )
                        for f in fields(self)
                        if _should_show_attr(f.name, getattr(self, f.name))
                    ]
                    return (
                        f"{self.__class__.__name__}(\n"
                        + "\n".join(field_strings)
                        + "\n)"
                    )

        if single_line.endswith("("):
            return single_line + ")"
        else:
            return single_line[:-2] + ")"  # Remove the last comma and space


@dataclass(**dataclass_settings)
class Auto:
    """This value will be defined when the report is saved."""

    ...


@dataclass(**dataclass_settings)
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


@dataclass(**dataclass_settings)
class Block(Base):
    ...

    # @classmethod
    # def from_model(cls, model: internal.BlockTypes):
    #     return None
    # cls = block_mapping.get(model.__class__)
    # return cls.from_model(model)


@dataclass(**dataclass_settings)
class UnknownBlock(Block):
    ...


@dataclass(**dataclass_settings)
class Heading(Block):
    @classmethod
    def from_model(cls, model: internal.Heading):
        texts = [text.text for text in model.children]
        text = "\n".join(texts)

        blocks = None
        if model.collapsed_children:
            blocks = [_lookup(b) for b in model.collapsed_children]

        if model.level == 1:
            return H1(text=text, collapsed_blocks=blocks)
        if model.level == 2:
            return H2(text=text, collapsed_blocks=blocks)
        if model.level == 3:
            return H3(text=text, collapsed_blocks=blocks)


@dataclass(**dataclass_settings)
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


@dataclass(**dataclass_settings)
class H1(Heading):
    text: str = ""
    collapsed_blocks: Optional[list["BlockTypes"]] = None

    def to_model(self):
        if (collapsed_children := self.collapsed_blocks) is not None:
            collapsed_children = [b.to_model() for b in collapsed_children]

        return internal.Heading(
            level=1,
            children=[internal.Text(text=self.text)],
            collapsed_children=collapsed_children,
        )


@dataclass(**dataclass_settings)
class H2(Block):
    text: str = ""
    collapsed_blocks: Optional[list["BlockTypes"]] = None

    def to_model(self):
        if (collapsed_children := self.collapsed_blocks) is not None:
            collapsed_children = [b.to_model() for b in collapsed_children]

        return internal.Heading(
            level=2,
            children=[internal.Text(text=self.text)],
            collapsed_children=collapsed_children,
        )


@dataclass(**dataclass_settings)
class H3(Block):
    text: str = ""
    collapsed_blocks: Optional[list["BlockTypes"]] = None

    def to_model(self):
        if (collapsed_children := self.collapsed_blocks) is not None:
            collapsed_children = [b.to_model() for b in collapsed_children]

        return internal.Heading(
            level=3,
            children=[internal.Text(text=self.text)],
            collapsed_children=collapsed_children,
        )


@dataclass(**dataclass_settings)
class Link:
    text: str
    url: AnyUrl


@dataclass(**dataclass_settings)
class InlineLatex:
    text: str


@dataclass(**dataclass_settings)
class P(Block):
    text: Union[str, list[Union[str, Link, InlineLatex]]] = ""

    def to_model(self):
        if isinstance(text := self.text, str):
            text = [text]

        texts = []
        for x in text:
            if isinstance(x, str):
                thing = internal.Text(text=x)
            elif isinstance(x, Link):
                thing = internal.InlineLink(
                    url=x.url,
                    children=internal.Text(text=x.text),
                )
            elif isinstance(x, InlineLatex):
                thing = internal.InlineLatex(content=x.text)
            texts.append(thing)

        if not all(isinstance(x, str) for x in texts):
            texts = [internal.Text()] + texts + [internal.Text()]

        return internal.Paragraph(children=texts)

    @classmethod
    def from_model(cls, model: internal.Paragraph):
        pieces = []
        for x in model.children:
            if isinstance(x, internal.Text):
                thing = x.text
            elif isinstance(x, internal.InlineLink):
                thing = Link(url=x.url, text=x.children[0].text)
            elif isinstance(x, internal.InlineLatex):
                thing = InlineLatex(text=x.content)
            pieces.append(thing)

        pieces = pieces[1:-1]

        if len(pieces) == 1 and isinstance(pieces[0], str):
            return cls(text=pieces[0])
        return cls(text=pieces)


@dataclass(**dataclass_settings)
class CheckedListItem:
    text: str = ""
    checked: bool = False

    def to_model(self):
        return internal.ListItem(
            children=[internal.Paragraph(children=[internal.Text(text=self.text)])],
            checked=self.checked,
        )


@dataclass(**dataclass_settings)
class OrderedListItem:
    text: str = ""

    def to_model(self):
        return internal.ListItem(
            children=[internal.Paragraph(children=[internal.Text(text=self.text)])],
            ordered=True,
        )


@dataclass(**dataclass_settings)
class UnorderedListItem:
    text: str = ""

    def to_model(self):
        return internal.ListItem(
            children=[internal.Paragraph(children=[internal.Text(text=self.text)])],
        )


@dataclass(**dataclass_settings)
class CheckedList(List):
    items: list[CheckedListItem] = Field(default_factory=lambda: [CheckedListItem()])

    def to_model(self):
        items = [x.to_model() for x in self.items]
        return internal.List(children=items)


@dataclass(**dataclass_settings)
class OrderedList(List):
    items: list[str] = Field(default_factory=lambda: [""])

    def to_model(self):
        items = [OrderedListItem(x) for x in self.items]
        children = [li.to_model() for li in items]
        return internal.List(children=children, ordered=True)


@dataclass(**dataclass_settings)
class UnorderedList(List):
    items: list[str] = Field(default_factory=lambda: [""])

    def to_model(self):
        items = [UnorderedListItem(x) for x in self.items]
        children = [li.to_model() for li in items]
        return internal.List(children=children)


@dataclass(**dataclass_settings)
class CodeBlock(Block):
    code: str = ""
    language: Optional[Language] = "python"

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


@dataclass(**dataclass_settings)
class MarkdownBlock(Block):
    text: str = ""

    def to_model(self):
        return internal.MarkdownBlock(content=self.text)

    @classmethod
    def from_model(cls, model: internal.MarkdownBlock):
        return cls(text=model.content)


@dataclass(**dataclass_settings)
class LatexBlock(Block):
    text: str = ""

    def to_model(self):
        return internal.LatexBlock(content=self.text)

    @classmethod
    def from_model(cls, model: internal.LatexBlock):
        return cls(text=model.content)


@dataclass(**dataclass_settings)
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


@dataclass(**dataclass_settings)
class CalloutBlock(Block):
    text: str = ""

    def to_model(self):
        return internal.CalloutBlock(
            children=[internal.CalloutLine(children=[internal.Text(text=self.text)])]
        )

    @classmethod
    def from_model(cls, model: internal.CalloutBlock):
        texts = [text.text for line in model.children for text in line.children]
        text = "\n".join(texts)
        return cls(text=text)


@dataclass(**dataclass_settings)
class HorizontalRule(Block):
    def to_model(self):
        return internal.HorizontalRule()

    @classmethod
    def from_model(cls, model: internal.HorizontalRule):
        return cls()


@dataclass(**dataclass_settings)
class Video(Block):
    url: AnyUrl

    def to_model(self):
        return internal.Video(url=self.url)

    @classmethod
    def from_model(cls, model: internal.Video):
        return cls(url=model.url)


@dataclass(**dataclass_settings)
class Spotify(Block):
    spotify_id: str

    def to_model(self):
        return internal.Spotify(spotify_id=self.spotify_id)

    @classmethod
    def from_model(cls, model: internal.Spotify):
        return cls(spotify_id=model.spotify_id)


@dataclass(**dataclass_settings)
class SoundCloud(Block):
    html: str

    def to_model(self):
        return internal.SoundCloud(html=self.html)

    @classmethod
    def from_model(cls, model: internal.SoundCloud):
        return cls(html=model.html)


@dataclass(**dataclass_settings)
class Gallery(Block):
    ids: list[str] = Field(default_factory=list)

    def to_model(self):
        return internal.Gallery(ids=self.ids)

    @classmethod
    def from_model(cls, model: internal.Gallery):
        return cls(ids=model.ids)


@dataclass(**dataclass_settings)
class CustomRunColors(Base):
    ...


@dataclass(**dataclass_settings)
class Order(Base):
    name: str
    ascending: bool = False

    def to_model(self):
        return internal.SortKey(
            key=internal.SortKeyKey(name=internal.get_frontend_name(self.name)),
            ascending=self.ascending,
        )

    @classmethod
    def from_model(cls, model: internal.SortKey):
        return cls(
            name=internal.get_backend_name(model.key.name),
            ascending=model.ascending,
        )


@dataclass(**dataclass_settings)
class Runset(Base):
    entity: Union[ReportEntity, str] = Field(default_factory=ReportEntity)
    project: Union[ReportProject, str] = Field(default_factory=ReportProject)
    name: str = "Run set"
    query: str = ""
    filters: Optional[str] = None
    groupby: list[str] = Field(default_factory=list)
    order: list[Order] = Field(
        default_factory=lambda: [Order("CreatedTimestamp", ascending=False)]
    )

    def to_model(self):
        entity = "" if isinstance(self.entity, ReportEntity) else self.entity
        project = "" if isinstance(self.project, ReportProject) else self.project
        # entity = self.entity
        # project = self.project

        return internal.Runset(
            project=internal.Project(entity_name=entity, name=project),
            name=self.name,
            filters=internal.expr_to_filters(self.filters),
            # TODO: Fix the groupings
            grouping=[
                internal.Key(name=internal.get_frontend_name(g)) for g in self.groupby
            ],
            sort=internal.Sort(keys=[o.to_model() for o in self.order]),
        )

    @classmethod
    def from_model(cls, model: internal.Runset):
        return cls(
            entity=model.project.entity_name,
            project=model.project.name,
            name=model.name,
            filters=internal.filters_to_expr(model.filters),
            groupby=[internal.get_backend_name(k.name) for k in model.grouping],
            order=[Order.from_model(s) for s in model.sort.keys],
        )


@dataclass(**dataclass_settings)
class Panel(Base):
    layout: Layout = Field(default_factory=Layout)


# @dataclass(**dataclass_settings)
# class PanelGridColumn(Base):
#     name: str
#     visible: bool = True
#     pinned: bool = False
#     width: int = 100


@dataclass(**dataclass_settings)
class PanelGrid(Block):
    runsets: list[Runset] = Field(default_factory=lambda: [Runset()])
    panels: list["PanelTypes"] = Field(default_factory=list)
    # custom_run_colors: Optional[CustomRunColors] = None
    active_runset: Optional[int] = None

    # columns: list[str] = Field(default_factory=list)

    def to_model(self):
        return internal.PanelGrid(
            metadata=internal.PanelGridMetadata(
                run_sets=[rs.to_model() for rs in self.runsets],
                panel_bank_section_config=internal.PanelBankSectionConfig(
                    panels=[p.to_model() for p in self.panels],
                ),
                # custom_run_colors=custom_run_colors,
            )
        )

    @classmethod
    def from_model(cls, model: internal.PanelGrid):
        return cls(
            runsets=[Runset.from_model(rs) for rs in model.metadata.run_sets],
            panels=[
                _lookup_panel(p)
                for p in model.metadata.panel_bank_section_config.panels
            ],
            active_runset=model.metadata.open_run_set,
        )

    @validator("runsets")
    def _validate_list_not_empty(cls, v):  # noqa: N805
        if len(v) < 1:
            raise ValueError("must have at least one runset")
        return v


@dataclass(**dataclass_settings)
class TableOfContents(Block):
    def to_model(self):
        return internal.TableOfContents()

    @classmethod
    def from_model(cls, model: internal.TableOfContents):
        return cls()


@dataclass(**dataclass_settings)
class Twitter(Block):
    ...


@dataclass(**dataclass_settings)
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
    CalloutBlock,
    Video,
    HorizontalRule,
    Spotify,
    SoundCloud,
    Gallery,
    PanelGrid,
    Block,
    TableOfContents,
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
    internal.Spotify: Spotify,
    internal.Twitter: Twitter,
    internal.SoundCloud: SoundCloud,
    internal.Block: Block,
}


@dataclass(**dataclass_settings)
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
            config=internal.LinePlotConfig(
                chart_title=self.title,
                x_axis=self.x,
                metrics=_listify(self.y),
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
            layout=self.layout.to_model(),
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
            layout=Layout.from_model(model.layout),
        )


@dataclass(**dataclass_settings)
class CustomGradientPoint:
    offset: int
    color: str

    @validator("color")
    def validate_hex_color(cls, v):  # noqa: N805
        if not re.match(r"^#(?:[0-9a-fA-F]{3}){1,2}$", v):
            raise ValueError("Invalid hex color code")
        return v

    def to_model(self):
        return internal.CustomGradientPoint(offset=self.offset, color=self.color)

    @classmethod
    def from_model(cls, model: internal.CustomGradientPoint):
        return cls(offset=model.offset, color=model.color)


@dataclass(**dataclass_settings)
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
    gradient: Optional[list[CustomGradientPoint]] = None
    font_size: Optional[FontSize] = None
    regression: Optional[bool] = None

    def to_model(self):
        if (custom_gradient := self.gradient) is not None:
            custom_gradient = [cgp.to_model() for cgp in self.gradient]

        return internal.ScatterPlot(
            config=internal.ScatterPlotConfig(
                chart_title=self.title,
                x_axis=self.x,
                y_axis=self.y,
                z_axis=self.z,
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
        )

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        if (gradient := model.config.custom_gradient) is not None:
            gradient = [CustomGradientPoint.from_model(cgp) for cgp in gradient]
        return cls(
            title=model.config.chart_title,
            x=model.config.x_axis,
            y=model.config.y_axis,
            z=model.config.z_axis,
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
        )


@dataclass(**dataclass_settings)
class BarPlot(Panel):
    title: Optional[str] = None
    metrics: list[str] = Field(default_factory=list)
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
        return internal.BarPlot(
            config=internal.BarPlotConfig(
                chart_title=self.title,
                metric=self.metrics,
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
        )

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        return cls(
            title=model.config.chart_title,
            metrics=model.config.metric,
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
        )


@dataclass(**dataclass_settings)
class ScalarChart(Panel):
    title: Optional[str] = None
    metric: str = ""
    groupby_aggfunc: Optional[GroupAgg] = None
    groupby_rangefunc: Optional[GroupArea] = None
    custom_expressions: Optional[str] = None
    legend_template: Optional[str] = None
    font_size: Optional[FontSize] = None

    def to_model(self):
        return internal.ScalarChart(
            config=internal.ScalarChartConfig(
                chart_title=self.title,
                metrics=[self.metric],
                group_agg=self.groupby_aggfunc,
                group_area=self.groupby_rangefunc,
                expressions=self.custom_expressions,
                legend_template=self.legend_template,
                font_size=self.font_size,
            ),
            layout=self.layout.to_model(),
        )

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        return cls(
            title=model.config.chart_title,
            metric=model.config.metrics[0],
            groupby_aggfunc=model.config.group_agg,
            groupby_rangefunc=model.config.group_area,
            custom_expressions=model.config.expressions,
            legend_template=model.config.legend_template,
            font_size=model.config.font_size,
            layout=Layout.from_model(model.layout),
        )


@dataclass(**dataclass_settings)
class CodeComparer(Panel):
    diff: CodeCompareDiff = "split"

    def to_model(self):
        return internal.CodeComparer(
            config=internal.CodeComparerConfig(diff=self.diff),
            layout=self.layout.to_model(),
        )

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        return cls(
            diff=model.config.diff,
            layout=Layout.from_model(model.layout),
        )


@dataclass(**dataclass_settings)
class ParallelCoordinatesPlotColumn(Base):
    accessor: str
    display_name: Optional[str] = None
    inverted: Optional[Literal[True]] = None
    log: Optional[Literal[True]] = None

    def to_model(self):
        return internal.Column(
            accessor=self.accessor,
            display_name=self.display_name,
            inverted=self.inverted,
            log=self.log,
        )

    @classmethod
    def from_model(cls, model: internal.Column):
        return cls(
            accessor=model.accessor,
            display_name=model.display_name,
            inverted=model.inverted,
            log=model.log,
        )


@dataclass(**dataclass_settings)
class ParallelCoordinatesPlot(Panel):
    columns: list[ParallelCoordinatesPlotColumn] = Field(default_factory=list)
    title: Optional[str] = None
    gradient: Optional[list] = None
    font_size: Optional[FontSize] = None

    def to_model(self):
        return internal.ParallelCoordinatesPlot(
            config=internal.ParallelCoordinatesPlotConfig(
                chart_title=self.title,
                columns=[c.to_model() for c in self.columns],
                custom_gradient=self.gradient,
                font_size=self.font_size,
            ),
            layout=self.layout.to_model(),
        )

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        return cls(
            columns=[
                ParallelCoordinatesPlotColumn.from_model(c)
                for c in model.config.columns
            ],
            title=model.config.chart_title,
            gradient=model.config.custom_gradient,
            font_size=model.config.font_size,
            layout=Layout.from_model(model.layout),
        )


@dataclass(**dataclass_settings)
class ParameterImportancePlot(Panel):
    with_respect_to: str = ""

    def to_model(self):
        return internal.ParameterImportancePlot(
            config=internal.ParameterImportancePlotConfig(
                target_key=self.with_respect_to
            ),
            layout=self.layout.to_model(),
        )

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        return cls(
            with_respect_to=model.config.target_key,
            layout=Layout.from_model(model.layout),
        )


@dataclass(**dataclass_settings)
class RunComparer(Panel):
    diff_only: Optional[Literal["split"]] = None

    def to_model(self):
        return internal.RunComparer(
            config=internal.RunComparerConfig(diff_only=self.diff_only),
            layout=self.layout.to_model(),
        )

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        return cls(
            diff_only=model.config.diff_only,
            layout=Layout.from_model(model.layout),
        )


@dataclass(**dataclass_settings)
class MediaBrowser(Panel):
    num_columns: Optional[int] = None
    media_keys: list[str] = Field(default_factory=list)

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


@dataclass(**dataclass_settings)
class MarkdownPanel(Panel):
    markdown: str = ""

    def to_model(self):
        return internal.MarkdownPanel(
            config=internal.MarkdownPanelConfig(value=self.markdown),
            layout=self.layout.to_model(),
        )

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        return cls(
            markdown=model.config.value,
            layout=Layout.from_model(model.layout),
        )


@dataclass(**dataclass_settings)
class ConfusionMatrix(Panel):
    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@dataclass(**dataclass_settings)
class DataFrames(Panel):
    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@dataclass(**dataclass_settings)
class MultiRunTable(Panel):
    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@dataclass(**dataclass_settings)
class Vega(Panel):
    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@dataclass(**dataclass_settings)
class CustomChart(Panel):
    query: dict = Field(default_factory=dict)
    chart_name: str = Field(default_factory=dict)
    chart_fields: dict = Field(default_factory=dict)
    chart_strings: dict = Field(default_factory=dict)

    def to_model(self):
        return internal.Vega2(
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

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        return cls(
            # query=model.config.user_query.query_fields,
            # chart_name=model.config.panel_def_id,
            # chart_fields=model.config.field_settings,
            # chart_strings=model.config.string_settings,
        )


@dataclass(**dataclass_settings)
class Vega3(Panel):
    def to_model(self):
        ...

    @classmethod
    def from_model(cls, model: internal.ScatterPlot):
        ...


@dataclass(**dataclass_settings)
class WeavePanel(Panel):
    ...


@dataclass(**dataclass_settings)
class Report(Base):
    project: str
    entity: str = DEFAULT_ENTITY
    title: str = "Untitled Report"
    description: str = ""
    id: Union[str, Auto] = Auto()
    blocks: list[BlockTypes] = Field(default_factory=list)

    def to_model(self):
        blocks_with_padding = [P()] + self.blocks + [P()]
        if isinstance((id := self.id), Auto):
            id = ""

        return internal.ReportViewspec(
            display_name=self.title,
            description=self.description,
            project=internal.Project(name=self.project, entity_name=self.entity),
            id=id,
            spec=internal.Spec(blocks=[b.to_model() for b in blocks_with_padding]),
        )

    @classmethod
    def from_model(cls, model: internal.ReportViewspec):
        blocks = model.spec.blocks[1:-1]
        if not (id := model.id):
            id = Auto()

        return cls(
            title=model.display_name,
            description=model.description,
            entity=model.project.entity_name,
            project=model.project.name,
            id=id,
            blocks=[_lookup(b) for b in blocks],
        )

    @property
    def url(self):
        if isinstance(self.id, Auto):
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

    # def to_html(self, height: int = 1024, hidden: bool = False) -> str:
    #     """Generate HTML containing an iframe displaying this report."""
    #     try:
    #         url = self.url + "?jupyter=true"
    #         style = f"border:none;width:100%;height:{height}px;"
    #         prefix = ""
    #         if hidden:
    #             style += "display:none;"
    #             prefix = wandb.sdk.lib.ipython.toggle_button("report")
    #         return prefix + f"<iframe src={url!r} style={style!r}></iframe>"
    #     except AttributeError:
    #         wandb.termlog("HTML repr will be available after you save the report!")

    # def _repr_html_(self) -> str:
    #     return self.to_html()


def _get_api():
    return wandb.Api()


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
    cls = block_mapping.get(block.__class__)
    return cls.from_model(block)


def _should_show_attr(k, v):
    if k.startswith("_"):
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
    cls = panel_mapping.get(panel.__class__)
    return cls.from_model(panel)


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
    # internal.Weave: Weave,
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
]


def _load_spec_from_url(url, as_model=False):
    import json

    vs = _url_to_viewspec(url)
    spec = vs["spec"]
    if as_model:
        return internal.Spec.model_validate(spec)
    return json.loads(spec)
