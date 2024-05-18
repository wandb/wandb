import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel
from wandb_gql import gql

import wandb

# these internal objects should be factored out into a separate module as a
# shared dependency between Workspaces and Reports API
from wandb.apis.reports.v2.internal import *
from wandb.apis.reports.v2.internal import (
    Filters,
    Key,
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


class OuterSectionSettings(WorkspaceAPIBaseModel):
    smoothing_weight: int = 0
    smoothing_type: str = "exponential"
    x_axis: str = "_step"
    ignore_outliers: bool = False
    use_runs_table_grouping_in_panels: bool = True
    x_axis_min: Optional[int] = None
    x_axis_max: Optional[int] = None
    color_run_names: Optional[bool] = None
    max_runs: Optional[int] = None
    point_visualization_method: Optional[
        Literal["bucketing-gorilla", "sampling"]
    ] = None
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


# class CustomRunColors(WorkspaceAPIBaseModel):
#     ref: Ref = Field(default_factory=Ref)


class OuterSection(WorkspaceAPIBaseModel):
    panel_bank_config: PanelBankConfig
    panel_bank_section_config: PanelBankSectionConfig

    # this is intentionally dict because it has arbitrary keys (the run ids)
    custom_run_colors: dict

    name: str = ""
    run_sets: list[Runset] = Field(default_factory=lambda: [Runset()])
    ref: Ref = Field(default_factory=Ref)
    settings: OuterSectionSettings = Field(default_factory=OuterSectionSettings)
    open_run_set: int = 0
    open_viz: bool = True


# unfortunate nomenclature... this is actually a workspace's view's spec...
class WorkspaceViewspec(WorkspaceAPIBaseModel):
    section: OuterSection
    viz_expanded: bool = False
    library_expanded: bool = True
    ref: Ref = Field(default_factory=Ref)


class View(WorkspaceAPIBaseModel):
    entity: str
    project: str
    display_name: str
    name: str
    id: str
    viewspec: WorkspaceViewspec


def upsert_view2(view: View, clone: bool = False) -> dict[str, Any]:
    query = gql(
        """
        mutation UpsertView2($id: ID, $entityName: String, $projectName: String, $type: String, $name: String, $displayName: String, $description: String, $spec: String, $parentId: ID, $locked: Boolean, $previewUrl: String, $coverUrl: String, $showcasedAt: DateTime, $createdUsing: ViewSource) {
        upsertView(
            input: {id: $id, entityName: $entityName, projectName: $projectName, name: $name, displayName: $displayName, description: $description, type: $type, spec: $spec, parentId: $parentId, locked: $locked, previewUrl: $previewUrl, coverUrl: $coverUrl, showcasedAt: $showcasedAt, createdUsing: $createdUsing}
        ) {
            view {
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
        updatedBy {
            id
            name
            username
            __typename
        }
        entityName
        project {
            id
            name
            entityName
            readOnly
            __typename
        }
        previewUrl
        coverUrl
        updatedAt
        createdAt
        starCount
        starred
        parentId
        locked
        viewCount
        showcasedAt
        alertSubscription {
            id
            __typename
        }
        accessTokens {
            id
            token
            view {
            id
            __typename
            }
            type
            emails
            createdBy {
            id
            username
            email
            name
            __typename
            }
            createdAt
            lastAccessedAt
            revokedAt
            projects {
            id
            name
            entityName
            __typename
            }
            __typename
        }
        __typename
        }
        """
    )

    api = wandb.Api()

    if clone or not (name := view.name):
        random_id = wandb.util.generate_id(11)
        name = _workspaceify(random_id)

    spec = view.viewspec.model_dump(by_alias=True, exclude_none=True)

    # hack: We're re-using Report API objects.  In the Report API, the value here
    # is expected to be None, but for Workspaces it's expected to be []
    spec["section"]["runSets"][0]["filters"]["filters"][0]["filters"] = []

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


def _get_view(entity: str, project: str, view_name: str) -> dict[str, Any]:
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
            "viewName": _workspaceify(view_name),
        },
    )
    return response["project"]["allViews"]["edges"][0]["node"]


def get_view(entity: str, project: str, view_name: str) -> View:
    view_dict = _get_view(entity, project, view_name)

    spec = view_dict["spec"]
    display_name = view_dict["displayName"]
    id = view_dict["id"]
    parsed_spec = WorkspaceViewspec.model_validate_json(spec)

    return View(
        entity=entity,
        project=project,
        display_name=display_name,
        name=view_name,
        id=id,
        viewspec=parsed_spec,
    )


def _workspaceify(name: str) -> str:
    return f"nw-{name}-v"


def _unworkspaceify(name: str) -> str:
    return name.replace("nw-", "").replace("-v", "")


import ast
from typing import Any, Dict

Expression = Dict[str, Any]

# Mapping custom operators to Python operators
OPERATOR_MAP = {
    "AND": "and",
    "OR": "or",
    "=": "==",
    "!=": "!=",
    "<": "<",
    "<=": "<=",
    ">": ">",
    ">=": ">=",
    "IN": "in",
    "NIN": "not in",
}

# Reverse mapping for parsing back to expression tree
REVERSE_OPERATOR_MAP = {
    "Eq": "=",
    "NotEq": "!=",
    "Lt": "<",
    "LtE": "<=",
    "Gt": ">",
    "GtE": ">=",
    "In": "IN",
    "NotIn": "NIN",
}


def expression_tree_to_code(expr: Filters) -> str:
    def parse_filter(filter: Filters) -> str:
        if filter.current:
            # Process 'current' key recursively
            current_expr = expression_tree_to_code(filter.current)
            if not current_expr:
                return ""
        key = filter.key
        if not key or not key.name:  # Check for empty or null name
            return ""
        key_str = f"{key.section}.{key.name}"
        op = OPERATOR_MAP[filter.op]
        value = repr(filter.value)
        if isinstance(filter.value, list):
            value = "[" + ", ".join(repr(v) for v in filter.value) + "]"
        return f"{key_str} {op} {value}"

    def parse_expression(expr: Filters) -> str:
        if expr.filters:
            filters = [parse_expression(f) for f in expr.filters]
            filters = [f for f in filters if f]  # Filter out empty strings
            op = OPERATOR_MAP[expr.op]
            return f" {op} ".join(f"({f})" for f in filters if f)
        else:
            return parse_filter(expr)

    return parse_expression(expr)


def code_to_expression_tree(code: str) -> Filters:
    if not code:  # Handle empty code string
        return Filters(op="AND", filters=[Filters()])

    def parse_key(key: str) -> Key:
        section, name = key.split(".")
        return Key(section=section, name=name)

    def parse_expr(node: ast.AST) -> Filters:
        if isinstance(node, ast.BoolOp):
            op = "AND" if isinstance(node.op, ast.And) else "OR"
            filters = [parse_expr(value) for value in node.values]
            return Filters(op=op, filters=filters)
        elif isinstance(node, ast.Compare):
            left = node.left
            if isinstance(left, ast.Attribute):
                key = f"{left.value.id}.{left.attr}"
            else:
                key = left.id
            key = parse_key(key)
            op = REVERSE_OPERATOR_MAP[node.ops[0].__class__.__name__]
            value = ast.literal_eval(node.comparators[0])
            return Filters(key=key, op=op, value=value, disabled=False)
        return Filters()

    expr_ast = ast.parse(code, mode="eval")
    return parse_expr(expr_ast.body)
