from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from itertools import chain
from typing import Literal

from pydantic import Field, TypeAdapter
from typing_extensions import Annotated

from wandb import util
from wandb.sdk.automations._typing import Base64Id, TypenameField
from wandb.sdk.automations._utils import _get_api
from wandb.sdk.automations.actions import AnyAction
from wandb.sdk.automations.base import Base
from wandb.sdk.automations.events import AnyEvent

reset_path = util.vendor_setup()

from wandb_gql import gql  # noqa: E402

_ORG_AUTOMATIONS_QUERY = gql(
    """
    fragment IntegrationFields on Integration {
        __typename
        ... on GenericWebhookIntegration {
            id
            name
            urlEndpoint
            secretRef
            accessTokenRef
            createdAt
        }
        ... on GitHubOAuthIntegration {
            id
        }
        ... on SlackIntegration {
            id
            teamName
            channelName
        }
    }

    fragment AutomationFields on Trigger {
        id
        createdAt
        createdBy {id username}
        updatedAt
        name
        description
        enabled
        scope {
            __typename
            ... on ArtifactPortfolio {id name}
            ... on ArtifactSequence {id name}
            ... on Project {id name}
        }
        triggeringCondition {
            __typename
            ... on FilterEventTriggeringCondition {
                eventType
                filter
            }
        }
        triggeredAction {
            __typename
            ... on QueueJobTriggeredAction {
                template
                queue {
                    __typename
                    id
                    name
                }
            }
            ... on NotificationTriggeredAction {
                title
                message
                severity
                integration {... IntegrationFields}
            }
            ... on GenericWebhookTriggeredAction {
                requestPayload
                integration {... IntegrationFields}
            }
        }
    }

    query TriggersInViewerOrgs ($entityName: String) {
        viewer(entityName: $entityName) {
            organizations {
                orgEntity {
                    projects {
                        edges {
                            node {
                                triggers {... AutomationFields}
                            }
                        }
                    }
                }
                teams {
                    projects {
                        edges {
                            node {
                                triggers {... AutomationFields}
                            }
                        }
                    }
                }
            }
        }
    }
    """
)


# ------------------------------------------------------------------------------
class User(Base):
    id: Base64Id
    username: str


# Scopes
class ArtifactPortfolioScope(Base):
    typename__: TypenameField[Literal["ArtifactPortfolio"]]
    id: Base64Id
    name: str


class ArtifactSequenceScope(Base):
    typename__: TypenameField[Literal["ArtifactSequence"]]
    id: Base64Id
    name: str


class ProjectScope(Base):
    typename__: TypenameField[Literal["Project"]]
    id: Base64Id
    name: str


AnyScope = Annotated[
    ArtifactPortfolioScope | ArtifactSequenceScope | ProjectScope,
    Field(discriminator="typename__"),
]


class ReadAutomation(Base):
    """A defined W&B automation."""

    id: Base64Id

    name: str
    description: str | None

    created_by: User
    created_at: datetime
    updated_at: datetime | None

    scope: AnyScope
    enabled: bool

    event: AnyEvent
    action: AnyAction


class CreateAutomation(Base):
    """A newly defined automation, to be prepared and sent by the client to the server."""

    name: str
    description: str | None

    scope: AnyScope
    enabled: bool

    event: AnyEvent
    action: AnyAction


ReadAutomationsAdapter = TypeAdapter(list[ReadAutomation])


def get_automations() -> Iterator[ReadAutomation]:
    api = _get_api()

    params = {"entityName": None}
    data = api.client.execute(_ORG_AUTOMATIONS_QUERY, variable_values=params)

    organizations = data["viewer"]["organizations"]
    entities = chain.from_iterable(
        [org["orgEntity"], *org["teams"]] for org in organizations
    )
    edges = chain.from_iterable(entity["projects"]["edges"] for entity in entities)
    projects = (edge["node"] for edge in edges)
    for proj in projects:
        yield from ReadAutomationsAdapter.validate_python(proj["triggers"])


# def get_automations_old(
#     entities: Iterable[str] | str | None = "wandb_Y72QKAKNEFI3G",
#     projects: Iterable[str] | str | None = "wandb-registry-model",
#     # entities: Iterable[str] | str | None = None,
#     # projects: Iterable[str] | str | None = None,
# ) -> Iterator[ReadAutomation]:
#     api = _get_api()
#
#     if (entities is None) and (projects is None):
#         all_orgs = get_orgs_info()
#         entity_project_pairs = iter_entity_project_pairs(all_orgs)
#     elif (entities is not None) and (projects is not None):
#         entity_project_pairs = product(
#             always_iterable(entities), always_iterable(projects)
#         )
#     else:
#         raise NotImplementedError(
#             "Filtering on specific entity or project names not yet implemented"
#         )
#
#     for entity, project in tqdm(
#         entity_project_pairs,
#         desc="Fetching automations from entity-project pairs",
#     ):
#         params = {"entityName": entity, "projectName": project}
#         data = api.client.execute(_FETCH_PROJECT_TRIGGERS, variable_values=params)
#         yield from ReadAutomationsAdapter.validate_python(data["project"]["triggers"])


# TODO: WIP
def new_automation(
    event_and_action: tuple[AnyEvent, AnyAction] | None = None,
    /,
    *,
    name: str,
    description: str | None = None,
    event: AnyEvent | None = None,
    action: AnyAction | None = None,
    enabled: bool = True,
) -> CreateAutomation:
    if event_and_action is not None:
        event, action = event_and_action

    return CreateAutomation(
        name=name,
        description=description,
        event=event,
        action=action,
        enabled=enabled,
    )
