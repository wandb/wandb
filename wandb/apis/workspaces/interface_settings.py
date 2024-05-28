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

#  This maps to PanelBankSettings in PanelBank/types.ts
@dataclass(config=dataclass_config, repr=False)
class WorkspaceSettings(Base):
    """Settings for the workspace. On the UI, these are inside the settings modal by clicking on the gear icon.

    Section and panel settings take precedence when defined. TODO - elaborate on specificity here
    
    Args:

    """

    auto_expand_panel_search_results: Optional[bool] = None
    
    # this is a protected setting - organize panels into sections by metric name
    auto_organize_prefix: Optional[Literal["group_first_prefix", "group_last_prefix"]] = None

    # Intentionally ignoring this setting 
    # this defines the name of the default section for the "Move panel to..." feature
    # default_move_to_section_name: Optional[str] = None

    show_empty_sections: bool = False
    # this is a protected setting
    sort_panels_alphabetically: bool = False
    
    search_query: Optional[str] = None
    
    # Intentionally ignoring this setting 
    # search_history: Optional[LList[Dict[Literal["query"], str]]] = Field(
    #     None, init=False, repr=False
    # )

    search_sections_open_mode: Optional[Literal["default", "auto-expand", "expand-all", "collapse-all"]] = None
    
    # This won't map 1-1 with PanelBankSettings in core/app but this is the direction we're heading towards
    line_plot_settings: LinePlotSettings = LinePlotSettings()

    @classmethod
    def from_model(cls, model: internal.Settings):
        return 

    def to_model(self):
        return 

# This is the user exposed interface. We will then map it to our internals
@dataclass
class LinePlotSettings(Base):
    """Settings that only affect line plots in a workspace.

    Args:

    """
    
    x_axis: str = "_step"  # fix this to use name map in future
    x_min: Optional[Annotated[float, Ge(0)]] = None
    x_max: Optional[Annotated[float, Ge(0)]] = None

    smoothing_type: internal.SmoothingType = "none"
    smoothing_weight: Annotated[float, Ge(0)] = 0

    # Outlier settings
    ignore_outliers: bool = False
    
    # if true, only show the highlighted run in companion plots
    highlighted_companion_run_only: Optional[bool] = None
    
    # this maps to Settings in panelsettings.ts
    max_runs: Optional[int] = None
    
    # Intentionally ignoring this setting 
    # This feature is still being rolled out on FE side, so should hold off
    # point_visualization_method: Optional[Literal["bucketing", "downsampling"]] = None
    
    # Panel settings
    remove_legends_from_panels: bool = False

    tooltip_number_of_runs: Optional[Literal["single", "default", "all_runs"]] = None
    color_tooltip_run_names: Optional[bool] = None

    @classmethod
    def from_model(cls, model):
        

    def to_model(self):
        


@dataclass
class SectionSettings(Base):
    """Settings for a section in a workspace. These are located in the CTAs that are visible when hovering next to `Add Panel` in a section.

    Args:
        layout (str): The layout of the panels in the section. "standard" follows the grid layout, while "custom" allows for per-panel layouts.
        columns (int): The number of columns in the layout.
        rows (int): The number of rows in the layout.

    """
    
    
    # these are the only line plot section level settings users can defined in UI right now
    # TODO - make this into it's own class?
    x_axis: str = "_step"  # fix this to use name map in future
    x_min: Optional[Annotated[float, Ge(0)]] = None
    x_max: Optional[Annotated[float, Ge(0)]] = None
    
    smoothing_type: internal.SmoothingType = "none"
    smoothing_weight: Annotated[float, Ge(0)] = 0

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


# maps to PanelBankFlowSectionConfig in PanelBank/types.ts
@dataclass
class SectionFlowConfig(Base):
    """

    Args:

    """

    snapToColumns: bool;
    columnsPerPage: bool;
    rowsPerPage: bool;
    gutterWidth: bool;
    boxWidth: bool;
    boxHeight: bool;
  

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


@dataclass(config=dataclass_config, repr=False)
class RunSetSettings(Base):
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
class RunSettings(Base):
    """Settings for a single run.

    Args:
        color (str): The color of the run in the UI.
        disabled (bool): Whether the run is disabled (eye closed in the UI).
    """

    color: str = ""  # hex, css color, or rgb
    disabled: bool = False

