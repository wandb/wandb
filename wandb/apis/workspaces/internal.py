import json
from typing import Any, Dict, Literal, Optional
from typing import List as LList

from annotated_types import Annotated, Ge
from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel
from wandb_gql import gql

import wandb

# these internal objects should be factored out into a separate module as a
# shared dependency between Workspaces and Reports API
from wandb.apis.reports.v2.internal import *  # noqa: F403
from wandb.apis.reports.v2.internal import (
    PanelBankConfig,
    PanelBankSectionConfig,
    Ref,
    Runset,
)


class WorkspaceAPIBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        use_enum_values=True,
        validate_assignment=True,
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )


class ViewspecSectionSettings(WorkspaceAPIBaseModel):
    smoothing_weight: Annotated[float, Ge(0)] = 0
    smoothing_type: str = "exponential"
    x_axis: str = "_step"
    ignore_outliers: bool = False
    use_runs_table_grouping_in_panels: bool = True
    x_axis_min: Optional[float] = None
    x_axis_max: Optional[float] = None
    color_run_names: Optional[bool] = None
    max_runs: Optional[int] = None
    point_visualization_method: Optional[Literal["bucketing-gorilla", "sampling"]] = (
        None
    )
    suppress_legends: Optional[bool] = None
    tooltip_number_of_runs: Optional[Literal["single", "default", "all_runs"]] = None

    @computed_field
    @property
    def smoothing_active(self) -> bool:
        return self.smoothing_type != "none" or self.smoothing_weight != 0

    @computed_field
    @property
    def x_axis_active(self) -> bool:
        return (
            self.x_axis != "_step"
            or self.x_axis_min is not None
            or self.x_axis_max is not None
        )


class ViewspecSection(WorkspaceAPIBaseModel):
    panel_bank_config: PanelBankConfig
    panel_bank_section_config: PanelBankSectionConfig

    # this is intentionally dict because it has arbitrary keys (the run ids)
    custom_run_colors: dict

    name: str = ""
    run_sets: LList[Runset] = Field(default_factory=lambda: [Runset()])
    ref: Ref = Field(default_factory=Ref)
    settings: ViewspecSectionSettings = Field(default_factory=ViewspecSectionSettings)
    open_run_set: int = 0
    open_viz: bool = True


# unfortunate nomenclature... this is actually a workspace's view's spec...
class WorkspaceViewspec(WorkspaceAPIBaseModel):
    section: ViewspecSection
    viz_expanded: bool = False
    library_expanded: bool = True
    ref: Ref = Field(default_factory=Ref)


class View(WorkspaceAPIBaseModel):
    entity: str
    project: str
    display_name: str
    name: str
    id: str
    spec: WorkspaceViewspec

    @classmethod
    def from_name(cls, entity: str, project: str, view_name: str) -> "View":
        view_dict = get_view_dict(entity, project, view_name)

        spec = view_dict["spec"]
        display_name = view_dict["displayName"]
        id = view_dict["id"]
        parsed_spec = WorkspaceViewspec.model_validate_json(spec)

        return cls(
            entity=entity,
            project=project,
            display_name=display_name,
            name=view_name,
            id=id,
            spec=parsed_spec,
        )


def upsert_view2(view: View, clone: bool = False) -> Dict[str, Any]:
    query = gql(
        """
        mutation UpsertView2($id: ID, $entityName: String, $projectName: String, $type: String, $name: String, $displayName: String, $description: String, $spec: String, $parentId: ID, $locked: Boolean, $previewUrl: String, $coverUrl: String, $showcasedAt: DateTime, $createdUsing: ViewSource) {
        upsertView(
            input: {id: $id, entityName: $entityName, projectName: $projectName, name: $name, displayName: $displayName, description: $description, type: $type, spec: $spec, parentId: $parentId, locked: $locked, previewUrl: $previewUrl, coverUrl: $coverUrl, showcasedAt: $showcasedAt, createdUsing: $createdUsing}
        ) {
            view {
            id
            id
            ...ViewFragmentMetadata2
            __typename
            }
            inserted
            __typename
        }
        }

        fragment ViewFragmentMetadata2 on View {
        id
                id
            ...ViewFragmentMetadata2
            __typename
            }
            inserted
            __typename
        }
        }

        fragment ViewFragmentMetadata2 on View {
        id
        name
        name
        displayName
        type
        description
        user {
            id
            username
            photoUrl
            admin
            name
            __typename
                name
        displayName
        type
        description
        user {
            id
            username
            photoUrl
            admin
            name
            __typename
            }
            inserted
          }
        }
        """
    )

    api = wandb.Api()

    if clone or not (name := view.name):
        random_id = wandb.util.generate_id(11)
        name = _to_workspace_view_name(random_id)

    spec = view.spec.model_dump(by_alias=True, exclude_none=True)

    # hack: We're re-using Report API objects.  In the Report API, the value here
    # is expected to be None, but for Workspaces it's expected to be []
    filters = spec["section"]["runSets"][0]["filters"]
    if "filters" in filters and len(filters["filters"]) > 0:
        filters["filters"][0]["filters"] = []

    variables = {
        "entityName": view.entity,
        "projectName": view.project,
        "name": name,
        "displayName": view.display_name,
        "type": "project-view",
        "description": "",
        "spec": json.dumps(spec),
        "locked": False,
    }

    # Adding the view Id breaks stuff for reasons I don't understand
    # if view.id:
    #     variables["id"] = view.id

    response = api.client.execute(query, variables)

    return response


def get_view_dict(entity: str, project: str, view_name: str) -> Dict[str, Any]:
    # Use this query because it let you use view_name instead of id
    query = gql(
        """
        query View($entityName: String, $name: String, $viewType: String = "runs", $userName: String, $viewName: String) {
            project(name: $name, entityName: $entityName) {
                allViews(viewType: $viewType, viewName: $viewName, userName: $userName) {
                    edges {
                        node {
                            id
                            displayName
                            spec
                        }
                    }
                }
            }
        }
        """
    )

    api = wandb.Api()

    response = api.client.execute(
        query,
        {
            "viewType": "project-view",
            "entityName": entity,
            "projectName": project,
            "name": project,
            "viewName": _to_workspace_view_name(view_name),
        },
    )

    edges = response.get("project", {}).get("allViews", {}).get("edges", [])

    try:
        view = edges[0]["node"]
    except IndexError:
        raise ValueError(f"Workspace `{view_name}` not found in project `{project}`")
    else:
        return view


def _to_workspace_view_name(name: str) -> str:
    return f"nw-{name}-v"


def _from_workspace_view_name(name: str) -> str:
    return name.replace("nw-", "").replace("-v", "")
