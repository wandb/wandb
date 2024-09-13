from __future__ import annotations

from enum import StrEnum
from textwrap import dedent
from typing import Any, Iterable, Iterator, Literal, Mapping

from pydantic import TypeAdapter, field_validator
from wandb_gql import gql

from wandb import Api
from wandb.apis.public import RetryingClient
from wandb.sdk.automations._typing import Base64Id, TypenameField
from wandb.sdk.automations.base import Base

# load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")


class UserInfo(Base):
    id: Base64Id
    username: str


class OrgType(StrEnum):
    ORGANIZATION = "ORGANIZATION"


class ProjectInfo(Base):
    typename__: TypenameField[Literal["Project"]]
    id: Base64Id
    name: str


class EntityInfo(Base):
    typename__: TypenameField[Literal["Entity"]]
    id: Base64Id
    name: str
    projects: list[ProjectInfo]

    @field_validator("projects", mode="before")
    @classmethod
    def _parse_edge_nodes(cls, v: Any) -> list[dict[str, Any]]:
        if isinstance(v, Mapping) and v.keys() == {"edges"}:
            return [edge["node"] for edge in v["edges"]]
        return v


class OrgInfo(Base):
    typename__: TypenameField[Literal["Organization"]]
    id: Base64Id
    name: str
    org_type: OrgType
    org_entity: EntityInfo
    teams: list[EntityInfo]


OrgInfoListAdapter = TypeAdapter(list[OrgInfo])


def get_orgs_info(entity: str | None = None) -> list[OrgInfo]:
    client = _client()

    params = {"entityName": entity}
    data = client.execute(_FETCH_ORGS_ENTITIES_PROJECTS, variable_values=params)

    viewer = data["viewer"]
    orgs = OrgInfoListAdapter.validate_python(viewer["organizations"])
    return orgs


def iter_entity_project_pairs(orgs: Iterable[OrgInfo]) -> Iterator[tuple[str, str]]:
    for org in orgs:
        # Yield from the org-entity, if any
        org_entity_name = org.org_entity.name
        for org_entity_project in org.org_entity.projects:
            yield org_entity_name, org_entity_project.name

        # Yield from org's teams, if any
        for entity in org.teams:
            entity_name = entity.name
            for entity_project in entity.projects:
                yield entity_name, entity_project.name


def _client() -> RetryingClient:
    api = Api()
    return api.client
    # api = Api(
    #     overrides={"base_url": "https://api.wandb.ai"},
    #     api_key=os.environ["WANDB_API_KEY"],
    # )
    # return api.client


_PROJECT_INFO_FRAGMENT = dedent(
    """
    fragment ProjectInfo on Project {
        __typename
        id
        internalId
        name
    }
    """
)
_FETCH_ORGS_ENTITIES_PROJECTS = gql(
    """
    query ViewerOrgsEntitiesProjects($entityName: String) {
        viewer(entityName: $entityName) {
            __typename
            id
            username
            organizations {
                __typename
                id
                name
                orgType
                orgEntity {
                    __typename
                    name
                    id
                    projects {
                        edges {
                            node {
                                __typename
                                id
                                name
                            }
                        }
                    }
                }
                teams {
                    __typename
                    id
                    name
                    projects {
                        edges {
                            node {
                                __typename
                                id
                                name
                            }
                        }
                    }
                }
            }
        }
    }
    """
)
