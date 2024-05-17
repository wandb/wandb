from typing import Literal, Optional
from urllib.parse import parse_qs, urlparse

from pydantic import AnyUrl, ConfigDict, Field
from pydantic.dataclasses import dataclass

import wandb
from wandb.apis.reports.v2 import expr_parsing
from wandb.apis.reports.v2.interface import OrderBy, PanelTypes, _lookup_panel

from . import internal

dataclass_config = ConfigDict(validate_assignment=True, extra="forbid", slots=True)


@dataclass(config=dataclass_config)
class Base:
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


@dataclass(config=dataclass_config)
class Section(Base):
    name: str
    panels: list[PanelTypes] = Field(default_factory=list)
    collapsed: bool = False

    section_settings: SectionSettings = Field(default_factory=SectionSettings)

    @classmethod
    def from_model(cls, model: internal.PanelBankConfigSectionsItem):
        return cls(
            name=model.name,
            panels=[_lookup_panel(p) for p in model.panels],
            collapsed=not model.is_open,
            section_settings=SectionSettings.from_model(model.flow_config),
        )

    def to_model(self):
        section_settings_model = self.section_settings.to_model()
        panel_models = [p.to_model() for p in self.panels]

        # Add warning that panel layout only works if they set section settings layout = "custom"

        return internal.PanelBankConfigSectionsItem(
            name=self.name,
            panels=panel_models,
            is_open=not self.collapsed,
            flow_config=section_settings_model,
        )


@dataclass(config=dataclass_config)
class ViewSettings(Base):
    x_axis: str = "_step"  # fix this to use name map in future
    # x_min: Optional[float] = None
    # x_max: Optional[float] = None
    smoothing_type: internal.SmoothingType = "none"
    smoothing_weight: float = 0
    ignore_outliers: bool = False

    @classmethod
    def from_model(cls, model: internal.OuterSectionSettings):
        return cls(
            x_axis=model.x_axis,
            # x_min=model.x_min,
            # x_max=model.x_max,
            smoothing_type=model.smoothing_type,
            smoothing_weight=model.smoothing_weight,
            ignore_outliers=model.ignore_outliers,
        )

    def to_model(self):
        return internal.OuterSectionSettings(
            x_axis=self.x_axis,
            # x_min=self.x_min,
            # x_max=self.x_max,
            smoothing_type=self.smoothing_type,
            smoothing_weight=self.smoothing_weight,
            ignore_outliers=self.ignore_outliers,
        )


@dataclass(config=dataclass_config)
class RunConfig(Base):
    color: Optional[str] = None
    disabled: bool = False


# maybe this can be the top-level object?
@dataclass(config=dataclass_config)
class View(Base):
    entity: str
    project: str
    name: str = ""
    sections: list[Section] = Field(default_factory=list)
    settings: ViewSettings = Field(default_factory=ViewSettings)

    # View runsets are tightly coupled to the view,
    # so we have them here instead of in their own object.
    # Also, the workspace only supports 1 runset at a time.
    runset_query: str = ""
    runset_filters: Optional[str] = ""
    runset_groupby: list[str] = Field(default_factory=list)
    runset_order: list[OrderBy] = Field(
        default_factory=lambda: [OrderBy("CreatedTimestamp", ascending=False)]
    )
    run_configs: dict[str, RunConfig] = Field(default_factory=dict)

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
            runset_query=model.viewspec.section.run_sets[0].search.query,
            runset_filters=expr_parsing.filters_to_expr(
                model.viewspec.section.run_sets[0].filters
            ),
            runset_groupby=[
                expr_parsing.to_frontend_name(k.name)
                for k in model.viewspec.section.run_sets[0].grouping
            ],
            runset_order=[
                OrderBy.from_model(s)
                for s in model.viewspec.section.run_sets[0].sort.keys
            ],
            run_configs=run_configs,
        )
        obj._internal_name = model.name
        obj._internal_id = model.id
        return obj

    def to_model(self):
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
                        sections=[s.to_model() for s in self.sections],
                    ),
                    panel_bank_section_config=internal.PanelBankSectionConfig(
                        pinned=False
                    ),
                    settings=self.settings.to_model(),
                    run_sets=[
                        internal.Runset(
                            search=internal.RunsetSearch(query=self.runset_query),
                            filters=expr_parsing.expr_to_filters(self.runset_filters),
                            grouping=[
                                internal.Key(name=expr_parsing.to_backend_name(g))
                                for g in self.runset_groupby
                            ],
                            sort=internal.Sort(
                                keys=[o.to_model() for o in self.runset_order]
                            ),
                            selections=internal.RunsetSelections(
                                tree=[
                                    id
                                    for id, config in self.run_configs.items()
                                    if config.disabled
                                ],
                            ),
                        ),
                    ],
                    custom_run_colors={
                        id: config.color for id, config in self.run_configs.items()
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

    def save(self, clone: bool = False):
        api = wandb.Api()
        resp = internal.upsert_view2(self.to_model(), clone)

        app_url = api.client.app_url
        entity = self.entity
        project = self.project
        name = internal._unworkspaceify(resp["upsertView"]["view"]["name"])

        workspace_url = f"{app_url}/{entity}/{project}?nw={name}"
        wandb.termlog(f"View saved: {workspace_url}")

        self._internal_name = name

        return self
