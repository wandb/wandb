from __future__ import annotations

from contextlib import contextmanager
from itertools import chain
from operator import itemgetter
from typing import TYPE_CHECKING, Iterator

# from gql import Client, gql
from pydantic import TypeAdapter
from wandb_gql import Client, gql

from wandb import Api
from wandb.sdk.automations.actions import (
    ActionType,
    NewNotificationActionInput,
    NewNotificationConfig,
    NewQueueJobActionInput,
    NewQueueJobConfig,
    NewWebhookActionInput,
    NewWebhookConfig,
)
from wandb.sdk.automations.automations import (
    Automation,
    DeletedAutomation,
    NewAutomation,
)
from wandb.sdk.automations.events import NewEventAndAction
from wandb.sdk.automations.generated.schema_gen import ArtifactCollection, Project

if TYPE_CHECKING:
    from wandb.sdk.automations.scopes import ScopeType

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


@contextmanager
def _gql_client() -> Iterator[Client]:
    yield Api().client


_AutomationsListAdapter = TypeAdapter(list[Automation])


def fetch(
    scope_type: str | ScopeType | None = None,
    user: str | None = None,
) -> Iterator[Automation]:
    from wandb.sdk.automations.scopes import ScopeType

    with _gql_client() as client:
        params = {"entityName": None}
        data = client.execute(_AUTOMATIONS_QUERY, variable_values=params)

        organizations = data["viewer"]["organizations"]
        entities = chain.from_iterable(
            [org_entity, *teams]
            for org_entity, teams in map(
                itemgetter("orgEntity", "teams"), organizations
            )
        )
        edges = chain.from_iterable(entity["projects"]["edges"] for entity in entities)
        projects = (edge["node"] for edge in edges)
        for proj in projects:
            for auto in _AutomationsListAdapter.validate_python(proj["triggers"]):
                if ((user is None) or (auto.created_by.username == user)) and (
                    (scope_type is None)
                    or (auto.scope.scope_type is ScopeType(scope_type))
                ):
                    yield auto


def create(
    new_automation: NewAutomation | None = None,
    # /,
    # *,
    # event: EventInput | None = None,
    # action: ActionInput | None = None,
    # name: str,
    # description: str | None = None,
    # enabled: bool = True,
) -> NewAutomation:
    with _gql_client() as client:
        data = client.execute(
            _CREATE_AUTOMATION,
            variable_values=new_automation.model_dump(mode="json"),
        )
        return Automation.model_validate(data["trigger"])


def define(
    event_and_action: NewEventAndAction,
    *,
    name: str,
    description: str | None,
    enabled: bool = True,
):
    from wandb.sdk.automations.scopes import ScopeType

    event, action = event_and_action

    match scope := event.scope:
        case ArtifactCollection() as coll:
            scope_type = ScopeType.ARTIFACT_COLLECTION
            scope_id = coll.id
        case Project() as proj:
            scope_type = ScopeType.PROJECT
            scope_id = _project_id(proj)
        case _:
            raise TypeError(
                f"Invalid scope object of type {type(scope).__name__!r}: {scope!r}"
            )

    match action:
        case NewQueueJobActionInput():
            action_type = ActionType.QUEUE_JOB
            action_config = NewQueueJobConfig(queue_job_action_input=action)
        case NewNotificationActionInput():
            action_type = ActionType.NOTIFICATION
            action_config = NewNotificationConfig(notification_action_input=action)
        case NewWebhookActionInput():
            action_type = ActionType.GENERIC_WEBHOOK
            action_config = NewWebhookConfig(generic_webhook_action_input=action)
        case _:
            raise TypeError(
                f"Unknown action type {type(action).__name__!r}: {action!r}"
            )

    return NewAutomation(
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


def _project_id(proj: Project) -> str:
    """Get the ID of the given project."""
    with _gql_client() as client:
        project_data = client.execute(
            _PROJECT_ID_BY_NAMES,
            variable_values={
                "name": proj.name,
                "entityName": proj.entity,
            },
        )
        return project_data["project"]["id"]


def delete(id_or_automation: str | Automation) -> DeletedAutomation:
    with _gql_client() as client:
        match id_or_automation:
            case Automation() as automation:
                params = {"id": automation.id}
            case str() as id_:
                params = {"id": id_}

        data = client.execute(_DELETE_AUTOMATION, variable_values=params)
        return DeletedAutomation.validate(data["deleteTrigger"])
