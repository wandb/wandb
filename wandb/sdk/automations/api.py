from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from contextlib import contextmanager
from itertools import chain
from operator import attrgetter, itemgetter
from typing import TYPE_CHECKING, Iterator

from more_itertools import one

# from gql import Client, gql
from pydantic import TypeAdapter
from rich.pretty import pretty_repr
from rich.table import Table
from wandb_gql import Client, gql

from wandb import Api
from wandb.sdk.automations import schemas_gen as gen
from wandb.sdk.automations.automations import (
    Automation,
    DeletedAutomation,
    NewAutomation,
)
from wandb.sdk.automations.events import NewEventAndAction

if TYPE_CHECKING:
    from wandb.sdk.automations.actions import ActionType
    from wandb.sdk.automations.events import EventType
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
        deleteTrigger(input: {
                triggerID: $id,
        }) {
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


_QUERY_SLACK_INTEGRATIONS = gql(
    """
    query Viewer {
        viewer {
            userEntity {
                integrations {
                    edges {
                        node {
                            id
                            ... on SlackIntegration {
                                id
                                teamName
                                channelName
                            }
                        }
                    }
                }
            }
        }
    }
    """
)


@contextmanager
def _gql_client() -> Iterator[Client]:
    yield Api().client


def make_table(automations: Sequence[Automation]) -> Table:
    from wandb.sdk.automations import events, scopes

    table = Table(
        title="Automations",
        title_justify="left",
        min_width=200,
        show_lines=True,
    )

    displayed_names = deque()
    for name, info in Automation.model_fields.items():
        if info.repr:
            displayed_names.append(name)
            if name.casefold() == "name":
                table.add_column(name, max_width=15, no_wrap=True)
            elif name.casefold() == "description":
                table.add_column(name, max_width=25)
            elif name.casefold() in {"scope", "event", "action"}:
                table.add_column(name, max_width=30)
            # elif name.casefold() == "enabled":
            #     table.add_column(name, max_width=5)
            else:
                table.add_column(name)

    get_fields = attrgetter(*displayed_names)
    for auto in automations:
        table.add_row(
            *(
                obj
                if isinstance(obj, str)
                else repr(obj)
                if isinstance(
                    obj,
                    (
                        scopes.BaseScope,
                        events.Event,
                        # actions.QueueJobAction,
                        # actions.NotificationAction,
                        # actions.WebhookAction,
                    ),
                )
                else pretty_repr(obj, max_depth=2, indent_size=1, max_length=2)
                for obj in get_fields(auto)
            )
        )

    return table


_AutomationsListAdapter = TypeAdapter(list[Automation])


def get_all(
    *,
    event: str | EventType | None = None,
    action: str | ActionType | None = None,
    scope: str | ScopeType | None = None,
    user: str | None = None,
) -> Iterator[Automation]:
    from wandb.sdk.automations import ActionType, EventType, ScopeType

    scope_type = None if (scope is None) else ScopeType(scope)
    event_type = None if (event is None) else EventType(event)
    action_type = None if (action is None) else ActionType(action)

    def _should_keep(automation: Automation) -> bool:
        return (
            ((user is None) or (automation.created_by.username == user))
            and ((scope_type is None) or (automation.scope.scope_type is scope_type))
            and ((event_type is None) or (automation.event.event_type is event_type))
            and (
                (action_type is None) or (automation.action.action_type is action_type)
            )
        )

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
        triggers = chain.from_iterable(proj["triggers"] for proj in projects)
        return list(
            filter(_should_keep, _AutomationsListAdapter.validate_python(triggers))
        )


def create(automation: NewAutomation) -> Automation:
    with _gql_client() as client:
        variable_values = automation.to_create_payload().model_dump()
        data = client.execute(_CREATE_AUTOMATION, variable_values=variable_values)
        return Automation.model_validate(data["createFilterTrigger"]["trigger"])


def define(
    event_and_action: NewEventAndAction,
    *,
    name: str,
    description: str | None,
    enabled: bool = True,
):
    event, action = event_and_action
    return NewAutomation(
        name=name,
        description=description,
        enabled=enabled,
        scope=event.scope,
        event=event,
        action=action,
    )


def _project_id(proj: gen.Project) -> str:
    """Get the ID of the given project."""
    with _gql_client() as client:
        variable_values = {
            "name": proj.name,
            "entityName": proj.entity,
        }
        data = client.execute(_PROJECT_ID_BY_NAMES, variable_values=variable_values)
        return data["project"]["id"]


class _TooManyError(ValueError):
    pass


class _TooFewError(ValueError):
    pass


def _slack_integration() -> gen.SlackIntegration:
    with _gql_client() as client:
        data = client.execute(_QUERY_SLACK_INTEGRATIONS)
        edges = data["viewer"]["userEntity"]["integrations"]["edges"]
        slack_integrations = [
            gen.SlackIntegration.model_validate(edge["node"]) for edge in edges
        ]
        try:
            return one(
                slack_integrations,
                too_short=_TooFew,
                too_long=_TooMany,
            )
        except _TooFew:
            raise RuntimeError(
                "No slack integration found!  You can set one up for your W&B user at: https://wandb.ai/settings"
            )
        except _TooMany:
            raise RuntimeError(
                f"Found multiple ({len(slack_integrations)}) Slack integrations: {slack_integrations!r}"
            )


def delete(id_or_automation: str | Automation) -> DeletedAutomation:
    with _gql_client() as client:
        match id_or_automation:
            case Automation() as automation:
                params = {"id": automation.id}
            case str() as id_:
                params = {"id": id_}

        data = client.execute(_DELETE_AUTOMATION, variable_values=params)
        return DeletedAutomation.validate(data["deleteTrigger"])
