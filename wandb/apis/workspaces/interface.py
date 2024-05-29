import os
from typing import Dict, Iterable, Literal, Optional
from typing import List as LList
from urllib.parse import parse_qs, urlparse, urlunparse

from annotated_types import Annotated, Ge
from pydantic import AnyUrl, ConfigDict, Field, PositiveInt
from pydantic.dataclasses import dataclass

import wandb
from wandb.apis.reports.v2.interface import PanelTypes, _lookup_panel
from wandb.apis.workspaces.interface_settings import RunSetSettings, SectionSettings, WorkspaceSettings

from . import expr, internal

dataclass_config = ConfigDict(validate_assignment=True, extra="forbid", slots=True)


def is_not_all_none(v):
    if v is None or v == "":
        return False
    if isinstance(v, Iterable) and not isinstance(v, str):
        return any(v not in (None, "") for v in v)
    return True


def is_not_internal(k):
    return not k.startswith("_")


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
            if (is_not_all_none(v) and is_not_internal(k)) or (should_show(v))
        )
        fields_str = ", ".join(fields)
        return f"{self.__class__.__name__}({fields_str})"

    def __rich_repr__(self):
        for k, v in self.__dict__.items():
            if (is_not_all_none(v) and is_not_internal(k)) or (should_show(v)):
                yield k, v

    @property
    def _model(self):
        return self.to_model()

    @property
    def _spec(self):
        return self._model.model_dump(by_alias=True, exclude_none=True)

@dataclass(config=dataclass_config, repr=False)
class Workspace(Base):
    """Represents a page in the UI to display experiment tracking.

    Args:
        entity (str): The entity name (usually user or team name).
        project (str): The project name.
        name (str): The name of the workspace.
        sections (LList[Section]): A list of sections.
        settings (WorkspaceSettings): Configuration settings for the workspace.
        run_settings (RunSettings): Configuration for run sets within the workspace.

    Attributes:
        url (str): The URL to the workspace in the W&B app.
        _internal_name (str): The internal name of the workspace.
        _internal_id (str): The internal ID of the workspace.
    """

    entity: str
    project: str
    
    workspace_name: Annotated[str, Field("")]
    workspace_sections: LList[WorkspaceSection] = Field(default_factory=list)
    workspace_settings: WorkspaceSettings = Field(default_factory=WorkspaceSettings)
    
    runset_settings: RunSetSettings = Field(default_factory=RunSetSettings)

    # this maps to view.name
    _internal_name: str = Field("", init=False, repr=False)
    # this maps to view.id
    _internal_id: str = Field("", init=False, repr=False)

    @classmethod
    def from_model(cls, model: internal.View):
        # move to util
        # construct configs from disjoint parts of settings
        run_settings = {}

        disabled_runs = model.viewspec.section.run_sets[0].selections.tree
        for id in disabled_runs:
            run_settings[id] = RunSettings(disabled=True)

        custom_run_colors = model.viewspec.section.custom_run_colors
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
            workspace_sections=[
                WorkspaceSection.from_model(s)
                for s in model.viewspec.section.panel_bank_config.sections
            ],
            workspace_settings=WorkspaceSettings.from_model(model.viewspec.section.settings),
            runset_settings=RunSetSettings(
                query=model.viewspec.section.run_sets[0].search.query,
                regex_query=bool(model.viewspec.section.run_sets[0].search.is_regex),
                filters=expr.expression_tree_to_filters(
                    model.viewspec.section.run_sets[0].filters
                ),
                groupby=[
                    expr.BaseMetric.from_key(v)
                    for v in model.viewspec.section.run_sets[0].grouping
                ],
                order=[
                    expr.Ordering.from_key(s)
                    for s in model.viewspec.section.run_sets[0].sort.keys
                ],
                run_settings=run_settings,
            ),
        )
        obj._internal_name = model.name
        obj._internal_id = model.id
        return obj

    def to_model(self):
        # maps to const spec = Normalize.denormalize(views.parts, view.partRef); in views/saga.ts
        # are we allowing users to defined multiple sections in a workspace??
        return internal.WorkspaceView(
            entity=self.entity,
            project=self.project,
            display_name=self.name,
            name=self._internal_name,
            id=self._internal_id,
            spec=internal.WorkspaceViewspec(
                section=internal.ViewSpecSection(
                    panel_bank_config=internal.PanelBankConfig(
                        state=1,
                        sections=get_workspace_sections(self),
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
        
    def get_workspace_sections(
        self,
    ):
        # do we really want to do this if setting is going to come soon? 
        # can we keep 1-1 parity for now? 
        # hack: create sections to hide auto-generated panels
        base_sections = [s.to_model() for s in self.sections]

        possible_missing_sections = set(("Hidden Panels", "Charts", "System"))
        base_section_names = set(s.name for s in self.sections)
        missing_section_names = possible_missing_sections - base_section_names

        hidden_sections = [
            WorkspaceSection(name, collapsed=True).to_model() for name in missing_section_names
        ]

        # explicit that these are workspace sections
        return base_sections + hidden_sections
        

    @classmethod
    def from_url(cls, url: AnyUrl):
        """Get a workspace from a URL."""
        
        # this is wrong
        
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
                "save workspace or explicitly pass `_internal_name` to get a url"
            )

        # this is also wrong

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
        self._internal_name = internal._unworkspaceify(
            resp["upsertView"]["view"]["name"]
        )

        wandb.termlog(f"View saved: {self.url}")
        return self


# this maps to PanelBankSectionConfig in PanelBank/types.ts
@dataclass(config=dataclass_config, repr=False)
class WorkspaceSection(Base):
    """Represents a section within a workspace.

    Args:
        name (str): The name of the section.
        panels (LList[PanelTypes]): A list of panels in the section.
        is_open (bool): Whether the section should be opened in UI.
        section_panel_settings (SectionPanelSettings): Settings for the panels in this section.
    """

    # TODO - why don't we need to Field(default_factory) stuff?
    name: str
    panels: LList[PanelTypes] = Field(default_factory=list)
    
    is_open: bool = True  
    # is_sorted: SectionPanelSorting;# TODO - typing
    is_pinned: bool = False
    
    layout_type: Literal['grid', 'flow'] = 'grid'
    flow_config: internal.FlowConfig = internal.FlowConfig()

    section_settings: SectionSettings = SectionSettings()

    @classmethod
    def from_model(cls, model: internal.PanelBankSectionConfig):

    def to_model(self):
       

