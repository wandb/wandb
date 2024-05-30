import os
from typing import Dict, Iterable, Literal, Optional
from typing import List as LList
from urllib.parse import parse_qs, urlparse, urlunparse

from annotated_types import Annotated, Ge
from pydantic import AnyUrl, ConfigDict, Field, PositiveInt
from pydantic.dataclasses import dataclass

import wandb
from wandb.apis.reports.v2.interface import PanelTypes, _lookup_panel

from . import expr, internal

dataclass_config = ConfigDict(validate_assignment=True, extra="forbid", slots=True)


def is_internal(k):
    return k.startswith("_")


def should_show(v):
    """This is a workaround because BaseMetric.__eq__ returns FilterExpr."""
    if isinstance(v, Iterable) and not isinstance(v, str):
        return any(should_show(x) for x in v)
    if isinstance(v, expr.BaseMetric):
        return True
    return False


@dataclass(config=dataclass_config, repr=False)
class Base:
    def __repr__(self):
        fields = (
            f"{k}={v!r}"
            for k, v in self.__dict__.items()
            if (not is_internal(k)) or (should_show(v))
        )
        fields_str = ", ".join(fields)
        return f"{self.__class__.__name__}({fields_str})"

    def __rich_repr__(self):
        for k, v in self.__dict__.items():
            if (not is_internal(k)) or (should_show(v)):
                yield k, v

    @property
    def _model(self):
        return self.to_model()

    @property
    def _spec(self):
        return self._model.model_dump(by_alias=True, exclude_none=True)


@dataclass(config=dataclass_config, repr=False)
class SectionLayoutSettings(Base):
    """Settings for a panels section, typically seen at the top right of the section in the UI.

    Args:
        layout (str): The layout of the panels in the section.  "standard" follows the grid layout, while "custom" allows for per-panel layouts.
        columns (int): The number of columns in the layout.
        rows (int): The number of rows in the layout.

    """

    layout: Literal["standard", "custom"] = "standard"
    columns: int = 3
    rows: int = 2

    @classmethod
    def from_model(cls, model: internal.FlowConfig):
        return cls(
            layout="standard" if model.snap_to_columns else "custom",
            columns=model.columns_per_page,
            rows=model.rows_per_page,
        )

    def to_model(self):
        return internal.FlowConfig(
            snap_to_columns=self.layout == "standard",
            columns_per_page=self.columns,
            rows_per_page=self.rows,
        )


@dataclass
class SectionPanelSettings(Base):
    # Axis settings
    x_axis: str = "Step"
    x_min: Optional[float] = None
    x_max: Optional[float] = None

    # Smoothing settings
    smoothing_type: internal.SmoothingType = "none"
    smoothing_weight: Annotated[float, Ge(0)] = 0

    @classmethod
    def from_model(cls, model: internal.LocalPanelSettings):
        x_axis = expr._convert_be_to_fe_metric_name(model.x_axis)

        return cls(
            x_axis=x_axis,
            x_min=model.x_axis_min,
            x_max=model.x_axis_max,
            smoothing_type=model.smoothing_type,
            smoothing_weight=model.smoothing_weight,
        )

    def to_model(self):
        x_axis = expr._convert_fe_to_be_metric_name(self.x_axis)

        return internal.LocalPanelSettings(
            x_axis=x_axis,
            x_axis_min=self.x_min,
            x_axis_max=self.x_max,
            smoothing_type=self.smoothing_type,
            smoothing_weight=self.smoothing_weight,
        )


@dataclass(config=dataclass_config, repr=False)
class Section(Base):
    """Represents a section in a workspace.

    Args:
        name (str): The name of the section.
        panels (LList[PanelTypes]): A list of panels in the section.
        is_open (bool): Whether the section is is_open.
        section_panel_settings (SectionPanelSettings): Settings for the panels in this section.
    """

    name: str
    panels: LList[PanelTypes] = Field(default_factory=list)
    is_open: bool = False
    section_layout_settings: SectionLayoutSettings = Field(
        default_factory=SectionLayoutSettings
    )
    section_panel_settings: SectionPanelSettings = Field(
        default_factory=SectionPanelSettings
    )

    @classmethod
    def from_model(cls, model: internal.PanelBankConfigSectionsItem):
        return cls(
            name=model.name,
            panels=[_lookup_panel(p) for p in model.panels],
            is_open=model.is_open,
            section_layout_settings=SectionLayoutSettings.from_model(model.flow_config),
            section_panel_settings=SectionPanelSettings.from_model(
                model.local_panel_settings
            ),
        )

    def to_model(self):
        panel_models = [p.to_model() for p in self.panels]
        flow_config = self.section_layout_settings.to_model()
        local_panel_settings = self.section_panel_settings.to_model()

        # Add warning that panel layout only works if they set section settings layout = "custom"

        return internal.PanelBankConfigSectionsItem(
            name=self.name,
            panels=panel_models,
            is_open=self.is_open,
            flow_config=flow_config,
            local_panel_settings=local_panel_settings,
        )


@dataclass(config=dataclass_config, repr=False)
class WorkspaceSettings(Base):
    """Settings for the workspace, typically seen at the top of the workspace in the UI.

    This object includes settings for the x-axis, smoothing, outliers, panels, tooltips, runs, and panel query bar.

    Settings applied here can be overrided by more granular Section and Panel settings.

    Args:
        x_axis (str): Global x-axis setting.
        x_min (float): The minimum value for the x-axis.
        x_max (float): The maximum value for the x-axis.
        smoothing_type (SmoothingType): The type of smoothing to apply to the data.
        smoothing_weight (float): The weighting factor for smoothing.
        ignore_outliers (bool): Whether to ignore outliers in charts
        remove_legends_from_panels (bool): Whether legends should be removed from panels.
        tooltip_number_of_runs (str): The number of runs to show in the tooltip.
        tooltip_color_run_names (bool): Whether to color run names in the tooltip.
        max_runs (int): The maximum number of runs to display.
        point_visualization_method (str): Controls sampling method for points
        panel_search_query (str): The query for the panel search bar.
        auto_expand_panel_search_results (bool): Whether to auto expand panel search results.
    """

    # Axis settings
    x_axis: str = "Step"
    x_min: Optional[float] = None
    x_max: Optional[float] = None

    # Smoothing settings
    smoothing_type: internal.SmoothingType = "none"
    smoothing_weight: Annotated[float, Ge(0)] = 0

    # Outlier settings
    ignore_outliers: bool = False

    # Panel settings
    remove_legends_from_panels: bool = False

    # Tooltip settings
    tooltip_number_of_runs: Literal["single", "default", "all_runs"] = "default"
    tooltip_color_run_names: bool = True

    # Run settings
    max_runs: PositiveInt = 10
    point_visualization_method: Literal["bucketing", "downsampling"] = "bucketing"

    # Panel query bar settings
    panel_search_query: str = ""
    auto_expand_panel_search_results: bool = False
    _panel_search_history: Optional[LList[Dict[Literal["query"], str]]] = Field(
        None, init=False, repr=False
    )

    @classmethod
    def from_model(cls, model: internal.ViewspecSectionSettings):
        x_axis = expr._convert_be_to_fe_metric_name(model.x_axis)
        point_viz_method = (
            "bucketing"
            if model.point_visualization_method == "bucketing-gorilla"
            else "downsampling"
        )

        return cls(
            x_axis=x_axis,
            x_min=model.x_axis_min,
            x_max=model.x_axis_max,
            smoothing_type=model.smoothing_type,
            smoothing_weight=model.smoothing_weight,
            ignore_outliers=model.ignore_outliers,
            remove_legends_from_panels=model.suppress_legends,
            tooltip_number_of_runs=model.tooltip_number_of_runs,
            tooltip_color_run_names=model.color_run_names,
            max_runs=model.max_runs,
            point_visualization_method=point_viz_method,
        )

    def to_model(self):
        x_axis = expr._convert_fe_to_be_metric_name(self.x_axis)
        point_viz_method = (
            "bucketing-gorilla"
            if self.point_visualization_method == "bucketing"
            else "sampling"
        )

        return internal.ViewspecSectionSettings(
            x_axis=x_axis,
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
class RunSettings(Base):
    """Settings for a run in a run set.

    Args:
        color (str): The color of the run in the UI.
        disabled (bool): Whether the run is disabled (eye closed in the UI).
    """

    color: str = ""  # hex, css color, or rgb
    disabled: bool = False


@dataclass(config=dataclass_config, repr=False)
class RunsetSettings(Base):
    """Settings for the runset (the left bar containing runs) in a workspace.

    Args:
        query (str): A query to filter the run set (can be a regex expr, see below).
        regex_query (bool): Whether the query is a regex query.
        filters (LList[FilterExpr]): A list of filters to apply to the runset.
        groupby (LList[MetricType]): A list of metrics to group the runset by.
        order (LList[Ordering]): A list of orderings to apply to the runset.
        run_settings (Dict[str, RunSettings]): A dictionary of run settings.
    """

    query: str = ""
    regex_query: bool = False
    filters: LList[expr.FilterExpr] = Field(default_factory=list)
    groupby: LList[expr.MetricType] = Field(default_factory=list)
    order: LList[expr.Ordering] = Field(default_factory=list)
    run_settings: Dict[str, RunSettings] = Field(default_factory=dict)


@dataclass(config=dataclass_config, repr=False)
class Workspace(Base):
    """Represents a W&B workspace, including sections, settings, and config for run sets.

    Args:
        entity (str): The entity name (usually user or team name).
        project (str): The project name.
        name (str): The name of the workspace.  Empty string will show "Untitled view" by default.
        sections (LList[Section]): A list of sections included in the workspace.
        settings (WorkspaceSettings): Configuration settings for the workspace.
        run_settings (RunSettings): Configuration for run sets within the workspace.

    Attributes:
        url (str): The URL to the workspace in the W&B app.
        _internal_name (str): The internal name of the workspace.
        _internal_id (str): The internal ID of the workspace.
    """

    entity: str
    project: str
    name: Annotated[str, Field("")]
    sections: LList[Section] = Field(default_factory=list)
    settings: WorkspaceSettings = Field(default_factory=WorkspaceSettings)
    runset_settings: RunsetSettings = Field(default_factory=RunsetSettings)

    _internal_name: str = Field("", init=False, repr=False)
    _internal_id: str = Field("", init=False, repr=False)

    @classmethod
    def from_model(cls, model: internal.View):
        # construct configs from disjoint parts of settings
        run_settings = {}

        disabled_runs = model.spec.section.run_sets[0].selections.tree
        for id in disabled_runs:
            run_settings[id] = RunSettings(disabled=True)

        custom_run_colors = model.spec.section.custom_run_colors
        for k, v in custom_run_colors.items():
            if k != "ref":
                id = k
                color = v

                if id not in run_settings:
                    run_settings[id] = RunSettings(color=color)
                else:
                    run_settings[id].color = color

        # then construct the Workspace object
        obj = cls(
            entity=model.entity,
            project=model.project,
            name=model.display_name,
            sections=[
                Section.from_model(s)
                for s in model.spec.section.panel_bank_config.sections
            ],
            settings=WorkspaceSettings.from_model(model.spec.section.settings),
            runset_settings=RunsetSettings(
                query=model.spec.section.run_sets[0].search.query,
                regex_query=bool(model.spec.section.run_sets[0].search.is_regex),
                filters=expr.expression_tree_to_filters(
                    model.spec.section.run_sets[0].filters
                ),
                groupby=[
                    expr.BaseMetric.from_key(v)
                    for v in model.spec.section.run_sets[0].grouping
                ],
                order=[
                    expr.Ordering.from_key(s)
                    for s in model.spec.section.run_sets[0].sort.keys
                ],
                run_settings=run_settings,
            ),
        )
        obj._internal_name = model.name
        obj._internal_id = model.id
        return obj

    def to_model(self):
        # hack: create sections to hide unnecessary panels
        base_sections = [s.to_model() for s in self.sections]

        possible_missing_sections = set(("Hidden Panels", "Charts", "System"))
        base_section_names = set(s.name for s in self.sections)
        missing_section_names = possible_missing_sections - base_section_names

        hidden_sections = [
            Section(name=name, is_open=False).to_model()
            for name in missing_section_names
        ]

        sections = base_sections + hidden_sections

        return internal.View(
            entity=self.entity,
            project=self.project,
            display_name=self.name,
            name=self._internal_name,
            id=self._internal_id,
            spec=internal.WorkspaceViewspec(
                section=internal.ViewspecSection(
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
                                query=self.runset_settings.query,
                                is_regex=self.runset_settings.regex_query,
                            ),
                            filters=expr.filters_to_expression_tree(
                                self.runset_settings.filters
                            ),
                            grouping=[g.to_key() for g in self.runset_settings.groupby],
                            sort=internal.Sort(
                                keys=[o.to_key() for o in self.runset_settings.order]
                            ),
                            selections=internal.RunsetSelections(
                                tree=[
                                    id
                                    for id, config in self.runset_settings.run_settings.items()
                                    if config.disabled
                                ],
                            ),
                        ),
                    ],
                    custom_run_colors={
                        id: config.color
                        for id, config in self.runset_settings.run_settings.items()
                    },
                ),
            ),
        )

    @classmethod
    def from_url(cls, url: AnyUrl):
        """Get a workspace from a URL."""
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        view_name = query_params.get("nw", [""])[0]

        _, entity, project = parsed_url.path.split("/")

        view = internal.View.from_name(entity, project, view_name)
        return cls.from_model(view)

    @property
    def url(self):
        if self._internal_name == "":
            raise AttributeError(
                "save workspace or explicitly pass `_internal_name` to get a url"
            )

        base = urlparse(wandb.Api().client.app_url)

        scheme = base.scheme
        netloc = base.netloc
        path = os.path.join(self.entity, self.project)
        params = ""
        query = f"nw={self._internal_name}"
        fragment = ""

        return urlunparse((scheme, netloc, path, params, query, fragment))

    def save(
        self,
        clone: bool = True,  # set clone to true for now because saving to the same workspace is broken
    ):
        """Save a workspace to W&B."""
        resp = internal.upsert_view2(self.to_model(), clone)
        self._internal_name = internal._from_workspace_view_name(
            resp["upsertView"]["view"]["name"]
        )

        wandb.termlog(f"View saved: {self.url}")
        return self
