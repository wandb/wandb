from __future__ import annotations

import re
from enum import Enum
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from wandb_gql import gql
from wandb_graphql.language import ast, visitor

from wandb._iterutils import one
from wandb.sdk.artifacts._validators import is_artifact_registry_project
from wandb.sdk.internal.internal_api import Api as InternalApi


def parse_s3_url_to_s3_uri(url) -> str:
    """Convert an S3 HTTP(S) URL to an S3 URI.

    Arguments:
        url (str): The S3 URL to convert, in the format
                   'http(s)://<bucket>.s3.<region>.amazonaws.com/<key>'.
                   or 'http(s)://<bucket>.s3.amazonaws.com/<key>'

    Returns:
        str: The corresponding S3 URI in the format 's3://<bucket>/<key>'.

    Raises:
        ValueError: If the provided URL is not a valid S3 URL.
    """
    # Regular expression to match S3 URL pattern
    s3_pattern = r"^https?://.*s3.*amazonaws\.com.*"
    parsed_url = urlparse(url)

    # Check if it's an S3 URL
    match = re.match(s3_pattern, parsed_url.geturl())
    if not match:
        raise ValueError("Invalid S3 URL")

    # Extract bucket name and key
    bucket_name, *_ = parsed_url.netloc.split(".")
    key = parsed_url.path.lstrip("/")

    # Construct the S3 URI
    s3_uri = f"s3://{bucket_name}/{key}"

    return s3_uri


class PathType(Enum):
    """We have lots of different paths users pass in to fetch artifacts, projects, etc.

    This enum is used for specifying what format the path is in given a string path.
    """

    PROJECT = "PROJECT"
    ARTIFACT = "ARTIFACT"


def parse_org_from_registry_path(path: str, path_type: PathType) -> str:
    """Parse the org from a registry path.

    Essentially fetching the "entity" from the path but for Registries the entity is actually the org.

    Args:
        path (str): The path to parse. Can be a project path <entity>/<project> or <project> or an
        artifact path like <entity>/<project>/<artifact> or <project>/<artifact> or <artifact>
        path_type (PathType): The type of path to parse.
    """
    parts = path.split("/")
    expected_parts = 3 if path_type == PathType.ARTIFACT else 2

    if len(parts) >= expected_parts:
        org, project = parts[:2]
        if is_artifact_registry_project(project):
            return org
    return ""


def fetch_org_from_settings_or_entity(
    settings: dict, default_entity: str | None = None
) -> str:
    """Fetch the org from either the settings or deriving it from the entity.

    Returns the org from the settings if available. If no org is passed in or set, the entity is used to fetch the org.

    Args:
        organization (str | None): The organization to fetch the org for.
        settings (dict): The settings to fetch the org for.
        default_entity (str | None): The default entity to fetch the org for.
    """
    if (organization := settings.get("organization")) is None:
        # Fetch the org via the Entity. Won't work if default entity is a personal entity and belongs to multiple orgs
        entity = settings.get("entity") or default_entity
        if entity is None:
            raise ValueError(
                "No entity specified and can't fetch organization from the entity"
            )
        entity_orgs = InternalApi()._fetch_orgs_and_org_entities_from_entity(entity)
        entity_org = one(
            entity_orgs,
            too_short=ValueError(
                "No organizations found for entity. Please specify an organization in the settings."
            ),
            too_long=ValueError(
                "Multiple organizations found for entity. Please specify an organization in the settings."
            ),
        )
        organization = entity_org.display_name
    return organization


class _GQLCompatRewriter(visitor.Visitor):
    """GraphQL AST visitor to rewrite queries/mutations to be compatible with older server versions."""

    omit_variables: set[str]
    omit_fragments: set[str]
    omit_fields: set[str]
    rename_fields: dict[str, str]

    def __init__(
        self,
        omit_variables: Iterable[str] | None = None,
        omit_fragments: Iterable[str] | None = None,
        omit_fields: Iterable[str] | None = None,
        rename_fields: Mapping[str, str] | None = None,
    ):
        self.omit_variables = set(omit_variables or ())
        self.omit_fragments = set(omit_fragments or ())
        self.omit_fields = set(omit_fields or ())
        self.rename_fields = dict(rename_fields or {})

    def enter_VariableDefinition(self, node: ast.VariableDefinition, *_, **__) -> Any:  # noqa: N802
        if node.variable.name.value in self.omit_variables:
            return visitor.REMOVE

    def enter_ObjectField(self, node: ast.ObjectField, *_, **__) -> Any:  # noqa: N802
        # For context, note that e.g.:
        #
        #   {description: $description
        #   ...}
        #
        # Is parsed as:
        #
        #   ObjectValue(fields=[
        #     ObjectField(name=Name(value='description'), value=Variable(name=Name(value='description'))),
        #   ...])
        if (
            isinstance(var := node.value, ast.Variable)
            and var.name.value in self.omit_variables
        ):
            return visitor.REMOVE

    def enter_Argument(self, node: ast.Argument, *_, **__) -> Any:  # noqa: N802
        if node.name.value in self.omit_variables:
            return visitor.REMOVE

    def enter_FragmentDefinition(self, node: ast.FragmentDefinition, *_, **__) -> Any:  # noqa: N802
        if node.name.value in self.omit_fragments:
            return visitor.REMOVE

    def enter_FragmentSpread(self, node: ast.FragmentSpread, *_, **__) -> Any:  # noqa: N802
        if node.name.value in self.omit_fragments:
            return visitor.REMOVE

    def enter_Field(self, node: ast.Field, *_, **__) -> Any:  # noqa: N802
        if node.name.value in self.omit_fields:
            return visitor.REMOVE
        if new_name := self.rename_fields.get(node.name.value):
            node.name.value = new_name
            return node

    def leave_Field(self, node: ast.Field, *_, **__) -> Any:  # noqa: N802
        # If the field had a selection set, but now it's empty, remove the field entirely
        if (node.selection_set is not None) and (not node.selection_set.selections):
            return visitor.REMOVE


def gql_compat(
    request_string: str,
    omit_variables: Iterable[str] | None = None,
    omit_fragments: Iterable[str] | None = None,
    omit_fields: Iterable[str] | None = None,
    rename_fields: Mapping[str, str] | None = None,
) -> ast.Document:
    """Rewrite a GraphQL request string to ensure compatibility with older server versions.

    Args:
        request_string (str): The GraphQL request string to rewrite.
        omit_variables (Iterable[str] | None): Names of variables to remove from the request string.
        omit_fragments (Iterable[str] | None): Names of fragments to remove from the request string.
        omit_fields (Iterable[str] | None): Names of fields to remove from the request string.
        rename_fields (Mapping[str, str] | None):
            A mapping of fields to rename in the request string, given as `{old_name -> new_name}`.

    Returns:
        str: Modified GraphQL request string with fragments on omitted types removed.
    """
    # Parse the request into a GraphQL AST
    doc = gql(request_string)

    if not (omit_variables or omit_fragments or omit_fields or rename_fields):
        return doc

    # Visit the AST with our visitor to filter out unwanted fragments
    rewriter = _GQLCompatRewriter(
        omit_variables=omit_variables,
        omit_fragments=omit_fragments,
        omit_fields=omit_fields,
        rename_fields=rename_fields,
    )
    return visitor.visit(doc, rewriter)
