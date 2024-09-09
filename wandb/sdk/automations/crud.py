from __future__ import annotations

from itertools import chain
from typing import Iterator

from wandb_gql import gql

from wandb.sdk.automations._utils import _client
from wandb.sdk.automations.actions import AnyAction
from wandb.sdk.automations.api import (
    CreateAutomation,
    ReadAutomation,
    ReadAutomationsAdapter,
)
from wandb.sdk.automations.events import AnyEvent

_ORG_AUTOMATIONS_QUERY_OLD = gql(
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


def query() -> Iterator[ReadAutomation]:
    client = _client()

    params = {"entityName": None}
    data = client.execute(_ORG_AUTOMATIONS_QUERY_OLD, variable_values=params)

    organizations = data["viewer"]["organizations"]
    entities = chain.from_iterable(
        [org["orgEntity"], *org["teams"]] for org in organizations
    )
    edges = chain.from_iterable(entity["projects"]["edges"] for entity in entities)
    projects = (edge["node"] for edge in edges)
    for proj in projects:
        yield from ReadAutomationsAdapter.validate_python(proj["triggers"])


def create(
    event_and_action: tuple[AnyEvent, AnyAction] | None = None,
    /,
    *,
    name: str,
    description: str | None = None,
    event: AnyEvent | None = None,
    action: AnyAction | None = None,
    enabled: bool = True,
) -> CreateAutomation:
    # TODO: WIP
    if event_and_action is not None:
        event, action = event_and_action

    return CreateAutomation(
        name=name,
        description=description,
        event=event,
        action=action,
        enabled=enabled,
    )


def delete():
    raise NotImplementedError
