import os
from typing import Annotated, Iterable, Literal, Optional
from urllib.parse import parse_qs, urlparse, urlunparse

from pydantic import AnyUrl, ConfigDict, Field
from pydantic.dataclasses import dataclass

import wandb
from wandb.apis.reports.v2 import expr_parsing
from wandb.apis.reports.v2.interface import OrderBy, PanelTypes, _get_api, _lookup_panel

from . import internal

dataclass_config = ConfigDict(validate_assignment=True, extra="forbid", slots=True)


def is_not_all_none(value):
    if value is None or value == "":
        return False
    if isinstance(value, Iterable) and not isinstance(value, str):
        return any(v not in (None, "") for v in value)
    return True


def is_not_internal(k):
    return not k.startswith("_")


@dataclass(config=dataclass_config, repr=False)
class Base:
    def __repr__(self):
        fields = (
            f"{k}={v!r}"
            for k, v in self.__dict__.items()
            if is_not_all_none(v) and is_not_internal(k)
        )
        fields_str = ", ".join(fields)
        return f"{self.__class__.__name__}({fields_str})"

    def __rich_repr__(self):
        for k, v in self.__dict__.items():
            if is_not_all_none(v) and is_not_internal(k):
                yield k, v

    @property
    def _model(self):
        return self.to_model()

    @property
    def _spec(self):
        return self._model.model_dump(by_alias=True, exclude_none=True)


@dataclass
class SectionSettings(Base):
    layout: Literal["standard", "custom"] = "standard"
    columns: int = 3
    rows: int = 2
    height: int = 300
    width: int = 460

    @classmethod
    def from_model(cls, model: internal.FlowConfig):
        return cls(
            layout="standard" if model.snap_to_columns else "custom",
            columns=model.columns_per_page,
            rows=model.rows_per_page,
            height=model.box_height,
            width=model.box_width,
        )

    def to_model(self):
        return internal.FlowConfig(
            snap_to_columns=self.layout == "standard",
            columns_per_page=self.columns,
            rows_per_page=self.rows,
            box_height=self.height,
            box_width=self.width,
        )


@dataclass(config=dataclass_config, repr=False)
class Section(Base):
    name: str
    panels: list[PanelTypes] = Field(default_factory=list)
    collapsed: bool = False

    # section_settings: SectionSettings = Field(default_factory=SectionSettings)
    section_settings: Optional[SectionSettings] = None

    @classmethod
    def from_model(cls, model: internal.PanelBankConfigSectionsItem):
        return cls(
            name=model.name,
            panels=[_lookup_panel(p) for p in model.panels],
            collapsed=not model.is_open,
            section_settings=SectionSettings.from_model(model.flow_config),
        )

    def to_model(self):
        if (section_settings := self.section_settings) is None:
            section_settings = SectionSettings()

        section_settings_model = section_settings.to_model()
        panel_models = [p.to_model() for p in self.panels]

        # Add warning that panel layout only works if they set section settings layout = "custom"

        return internal.PanelBankConfigSectionsItem(
            name=self.name,
            panels=panel_models,
            is_open=not self.collapsed,
            flow_config=section_settings_model,
        )


@dataclass(config=dataclass_config, repr=False)
class ViewSettings(Base):
    # Axis settings
    x_axis: str = "_step"  # fix this to use name map in future
    x_min: Optional[float] = None
    x_max: Optional[float] = None

    # Smoothing settings
    smoothing_type: internal.SmoothingType = "none"
    smoothing_weight: float = 0

    # Outlier settings
    ignore_outliers: bool = False

    # Panel settings
    remove_legends_from_panels: bool = False

    # Tooltip settings
    tooltip_number_of_runs: Literal["single", "default", "all_runs"] = "default"
    tooltip_color_run_names: bool = True

    # Run settings
    max_runs: int = 10
    point_visualization_method: Literal["bucketing", "downsampling"] = "bucketing"

    @classmethod
    def from_model(cls, model: internal.OuterSectionSettings):
        point_viz_method = (
            "bucketing"
            if model.point_visualization_method == "bucketing-gorilla"
            else "downsampling"
        )

        return cls(
            x_axis=model.x_axis,
            x_min=model.x_axis_min,
            x_max=model.x_axis_max,
            smoothing_type=model.smoothing_type,
            smoothing_weight=model.smoothing_weight,
            ignore_outliers=model.ignore_outliers,
            remove_legends_from_panels=model.settings.suppress_legends,
            tooltip_number_of_runs=model.settings.tooltip_number_of_runs,
            tooltip_color_run_names=model.settings.color_run_names,
            max_runs=model.settings.max_runs,
            point_visualization_method=point_viz_method,
        )

    def to_model(self):
        point_viz_method = (
            "bucketing-gorilla"
            if self.point_visualization_method == "bucketing"
            else "sampling"
        )

        return internal.OuterSectionSettings(
            x_axis=self.x_axis,
            x_axis_min=self.x_min,
            x_axis_max=self.x_max,
            smoothing_type=self.smoothing_type,
            smoothing_weight=self.smoothing_weight,
            ignore_outliers=self.ignore_outliers,
            suppress_legends=self.remove_legends_from_panels,
            tooltip_number_of_runs=self.tooltip_number_of_runs,
            color_run_names=self.tooltip_color_run_names,
            max_runs=self.max_runs,
            point_visualization_method=point_viz_method,
        )


@dataclass(config=dataclass_config, repr=False)
class RunConfig(Base):
    color: str = ""  # hex, css color, or rgb
    disabled: bool = False


@dataclass(config=dataclass_config, repr=False)
class RunsetConfig(Base):
    query: str = ""
    regex_query: bool = False
    filters: Optional[str] = ""
    groupby: list[str] = Field(default_factory=list)
    order: list[OrderBy] = Field(
        default_factory=lambda: [OrderBy("CreatedTimestamp", ascending=False)]
    )

    run_configs: dict[str, RunConfig] = Field(default_factory=dict)


@dataclass(config=dataclass_config, repr=False)
class View(Base):
    """Represents a wandb workspace, including sections, settings, and config for run sets.

    Attributes:
        entity (str): The entity name (usually user or team name).
        project (str): The project name.
        name (str): The name of the view.  Empty string will show "Untitled view" by default.
        sections (List[Section]): A list of sections included in the view.
        settings (ViewSettings): Configuration settings for the view.
        runset_config (RunsetConfig): Configuration for run sets within the view.
    """

    entity: str
    project: str
    name: Annotated[str, Field("")]
    sections: list[Section] = Field(default_factory=list)
    settings: ViewSettings = Field(default_factory=ViewSettings)
    runset_config: RunsetConfig = Field(default_factory=RunsetConfig)

    _internal_name: str = Field("", init=False, repr=False)
    _internal_id: str = Field("", init=False, repr=False)

    @classmethod
    def from_model(cls, model: internal.View):
        # construct configs from disjoint parts of settings
        run_configs = {}

        disabled_runs = model.viewspec.section.run_sets[0].selections.tree
        for id in disabled_runs:
            run_configs[id] = RunConfig(disabled=True)

        custom_run_colors = model.viewspec.section.custom_run_colors
        for k, v in custom_run_colors.items():
            if k != "ref":
                id = k
                color = v

                if id not in run_configs:
                    run_configs[id] = RunConfig(color=color)
                else:
                    run_configs[id].color = color

        # then construct the View object
        obj = cls(
            entity=model.entity,
            project=model.project,
            name=model.display_name,
            sections=[
                Section.from_model(s)
                for s in model.viewspec.section.panel_bank_config.sections
            ],
            runset_config=RunsetConfig(
                query=model.viewspec.section.run_sets[0].search.query,
                regex_query=model.viewspec.section.run_sets[0].search.is_regex,
                filters=internal.expression_tree_to_code(
                    model.viewspec.section.run_sets[0].filters
                ),
                groupby=[
                    expr_parsing.to_frontend_name(k.name)
                    for k in model.viewspec.section.run_sets[0].grouping
                ],
                order=[
                    OrderBy.from_model(s)
                    for s in model.viewspec.section.run_sets[0].sort.keys
                ],
                run_configs=run_configs,
            ),
        )
        obj._internal_name = model.name
        obj._internal_id = model.id
        return obj

    def to_model(self):
        # hack: create sections to hide unnecessary panels
        base_sections = [s.to_model() for s in self.sections]
        hidden_sections = [
            Section("Hidden Panels", collapsed=True, panels=[]).to_model(),
            Section("Charts", collapsed=True, panels=[]).to_model(),
        ]
        sections = base_sections + hidden_sections

        return internal.View(
            entity=self.entity,
            project=self.project,
            display_name=self.name,
            name=self._internal_name,
            id=self._internal_id,
            viewspec=internal.WorkspaceViewspec(
                section=internal.OuterSection(
                    panel_bank_config=internal.PanelBankConfig(
                        state=1,
                        sections=sections,
                    ),
                    panel_bank_section_config=internal.PanelBankSectionConfig(
                        pinned=False
                    ),
                    settings=self.settings.to_model(),
                    run_sets=[
                        internal.Runset(
                            search=internal.RunsetSearch(
                                query=self.runset_config.query,
                                is_regex=self.runset_config.regex_query,
                            ),
                            filters=internal.code_to_expression_tree(
                                self.runset_config.filters
                            ),
                            grouping=[
                                internal.Key(name=expr_parsing.to_backend_name(g))
                                for g in self.runset_config.groupby
                            ],
                            sort=internal.Sort(
                                keys=[o.to_model() for o in self.runset_config.order]
                            ),
                            selections=internal.RunsetSelections(
                                tree=[
                                    id
                                    for id, config in self.runset_config.run_configs.items()
                                    if config.disabled
                                ],
                            ),
                        ),
                    ],
                    custom_run_colors={
                        id: config.color
                        for id, config in self.runset_config.run_configs.items()
                    },
                ),
            ),
        )

    @classmethod
    def from_url(cls, url: AnyUrl):
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        view_name = query_params.get("nw", [""])[0]

        _, entity, project = parsed_url.path.split("/")

        view = internal.get_view(entity, project, view_name)
        return cls.from_model(view)

    @property
    def url(self):
        if self._internal_name == "":
            raise AttributeError(
                "save view or explicitly pass `_internal_name` to get a url"
            )

        base = urlparse(_get_api().client.app_url)

        scheme = base.scheme
        netloc = base.netloc
        path = os.path.join(self.entity, self.project)
        params = ""
        query = f"nw={self._internal_name}"
        fragment = ""

        return urlunparse((scheme, netloc, path, params, query, fragment))

    def save(
        self,
        clone: bool = True,  # set clone to true for now because saving to the same view is broken
    ):
        resp = internal.upsert_view2(self.to_model(), clone)
        self._internal_name = internal._unworkspaceify(
            resp["upsertView"]["view"]["name"]
        )

        wandb.termlog(f"View saved: {self.url}")
        return self
