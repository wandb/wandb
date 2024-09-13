from __future__ import annotations

from contextlib import contextmanager
from itertools import chain
from operator import itemgetter
from typing import Any, Iterator

# from gql import Client, gql
from pydantic import TypeAdapter
from wandb_gql import Client, gql

from wandb import Api
from wandb.apis.public import ArtifactCollection, Project
from wandb.sdk.automations.actions import (
    ActionInput,
    NotificationActionInput,
    QueueJobActionInput,
    WebhookActionInput,
)
from wandb.sdk.automations.automations import (
    Automation,
    CreateAutomationInput,
    DeletedAutomation,
)
from wandb.sdk.automations.events import EventInput

_AUTOMATIONS_QUERY = gql(
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

_DELETE_AUTOMATION = gql(
    """
    mutation DeleteAutomation($id: ID!) {
        deleteTrigger(
            triggerID: $id,
        ) {
            success
            clientMutationId
        }
    }
    """
)

_CREATE_AUTOMATION = gql(
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

    mutation CreateAutomation(
        $name: String!,
        $description: String,
        $triggeringEventType: EventTriggeringConditionType!,
        $scopeType: TriggerScopeType!
        $scopeID: ID!
        $eventFilter: JSONString!
        $triggeredActionType: TriggeredActionType!
        $triggeredActionConfig: TriggeredActionConfig!
        $enabled: Boolean!
    ) {
        createFilterTrigger(input: {
            name: $name,
            description: $description,
            triggeringEventType: $triggeringEventType,
            scopeType: $scopeType,
            scopeID: $scopeID,
            eventFilter: $eventFilter,
            triggeredActionType: $triggeredActionType,
            triggeredActionConfig: $triggeredActionConfig,
            enabled: $enabled,
        }) {
            trigger {
                ...AutomationFields
            }
            clientMutationId
        }
    }
    """
)

_PROJECT_ID_BY_NAMES = gql(
    """
    query ProjectIDByName($name: String!, $entityName: String!) {
        project(name: $name, entityName: $entityName) {
            id
        }
    }
    """
)

# client = _client()


@contextmanager
def gql_client() -> Iterator[Client]:
    yield Api().client


_AutomationsListAdapter = TypeAdapter(list[Automation])


def query(client, user: str | None = None) -> Iterator[Automation]:
    # with gql_client() as client:
    params = {"entityName": None}
    data = client.execute(_AUTOMATIONS_QUERY, variable_values=params)

    organizations = data["viewer"]["organizations"]
    entities = chain.from_iterable(
        [org_entity, *teams]
        for org_entity, teams in map(itemgetter("orgEntity", "teams"), organizations)
    )
    edges = chain.from_iterable(entity["projects"]["edges"] for entity in entities)
    projects = (edge["node"] for edge in edges)
    for proj in projects:
        for auto in _AutomationsListAdapter.validate_python(proj["triggers"]):
            if (user is None) or (auto.created_by.username == user):
                yield auto


def create(
    client,
    event_and_action: tuple[EventInput, ActionInput] | None = None,
    /,
    *,
    name: str,
    description: str | None = None,
    # scope: ArtifactCollection | Project = None,
    enabled: bool = True,
) -> CreateAutomationInput:
    # with gql_client() as client:
    # # TODO: WIP
    event, action = event_and_action

    match event.scope:
        case ArtifactCollection() as coll:
            scope_type = "ARTIFACT_COLLECTION"
            scope_id = coll.id
        case Project() as proj:
            scope_type = "PROJECT"

            project_data = client.execute(
                _PROJECT_ID_BY_NAMES,
                variable_values={
                    "name": proj.name,
                    "entityName": proj.entity,
                },
            )
            project_id = project_data["project"]["id"]

            scope_id = project_id
        case _:
            raise TypeError(
                f"Invalid scope object of type {type(event.scope).__name__!r}: {event.scope!r}"
            )

    match action:
        case QueueJobActionInput():
            action_type = "QUEUE_JOB"
            # TODO: put together queue job action config
            raise NotImplementedError
        case NotificationActionInput():
            action_type = "NOTIFICATION"
            action_config = {
                "notificationActionInput": action.model_dump(),
                # "notificationActionInput": {
                #     "integrationID": action.integration_id,
                #     "title": action.title,
                #     "message": action.message,
                #     "severity": action.severity.value,
                # },
            }
        case WebhookActionInput():
            action_type = "GENERIC_WEBHOOK"
            action_config = {
                "genericWebhookActionInput": action.model_dump(),
                # "genericWebhookActionInput": {
                #     "integrationID": action.integration_id,
                #     "requestPayload": action.request_payload,
                # },
            }
        case _:
            raise TypeError(
                f"Unknown action type {type(action).__name__!r}: {action!r}"
            )

    params = CreateAutomationInput(
        name=name,
        description=description,
        enabled=enabled,
        # ------------------------------------------------------------------------------
        scope_type=scope_type,
        scope_id=scope_id,
        # ------------------------------------------------------------------------------
        triggering_event_type=event.event_type,
        event_filter=event.filter,
        # ------------------------------------------------------------------------------
        triggered_action_type=action_type,
        triggered_action_config=action_config,
    )

    data = client.execute(
        _CREATE_AUTOMATION,
        variable_values=params.model_dump(mode="json"),
    )
    return Automation.model_validate(data["trigger"])


def delete(
    client,
    id_: Any,
) -> DeletedAutomation:
    # with gql_client() as client:
    params = {"id": id_}
    data = client.execute(_DELETE_AUTOMATION, variable_values=params)
    return DeletedAutomation.validate(data["deleteTrigger"])
