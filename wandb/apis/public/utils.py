import re
from enum import Enum
from functools import cache
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

from wandb_gql import gql

import wandb
from wandb._iterutils import one
from wandb.apis.public._generated.operations import SERVER_FEATURES_QUERY_GQL
from wandb.apis.public._generated.server_features_query import ServerFeaturesQuery
from wandb.proto.v3.wandb_internal_pb2 import ServerFeature
from wandb.sdk.artifacts._validators import is_artifact_registry_project
from wandb.sdk.internal.internal_api import Api as InternalApi

if TYPE_CHECKING:
    from wandb_gql import Client


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
    settings: dict, default_entity: Optional[str] = None
) -> str:
    """Fetch the org from either the settings or deriving it from the entity.

    Returns the org from the settings if available. If no org is passed in or set, the entity is used to fetch the org.

    Args:
        organization (str | None): The organization to fetch the org for.
        settings (dict): The settings to fetch the org for.
        default_entity (str | None): The default entity to fetch the org for.
    """
    organization = settings["organization"]
    if organization is None:
        # Fetch the org via the Entity. Won't work if default entity is a personal entity and belongs to multiple orgs
        entity = settings["entity"] or default_entity
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


@cache
def check_server_feature(client: "Client", feature: ServerFeature) -> bool:
    """Check if a server feature is enabled.

    Args:
        feature (ServerFeature): The feature to check.

    Returns:
        bool: True if the feature is enabled, False otherwise.
    """
    # Validate that feature is a valid ServerFeature
    if not ServerFeature.Name(feature):
        raise ValueError(
            f"Invalid feature: {feature}. Must be a valid ServerFeature enum value."
        )

    try:
        response = client.execute(gql(SERVER_FEATURES_QUERY_GQL))
    except Exception as e:
        wandb.termwarn(
            "Possible that the server doesn't support the feature query, please make sure you are on an updated server release version",
            e,
        )
        return False
    query = ServerFeaturesQuery.model_validate(response)

    feature_name = ServerFeature.Name(feature)
    if query.server_info and query.server_info.features:
        for feature_info in query.server_info.features:
            if feature_info and feature_info.name == feature_name:
                return feature_info.is_enabled

    return False
