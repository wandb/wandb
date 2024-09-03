from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from more_itertools import always_iterable
from pydantic import Field, TypeAdapter
from tqdm.auto import tqdm

from wandb import util
from wandb.sdk.automations._typing import Base64Id
from wandb.sdk.automations._utils import (
    _get_api,
    get_orgs_info,
    iter_entity_project_pairs,
)
from wandb.sdk.automations.actions import AnyAction
from wandb.sdk.automations.base import Base
from wandb.sdk.automations.events import AnyEvent

reset_path = util.vendor_setup()

from wandb_gql import gql  # noqa: E402

_FETCH_PROJECT_TRIGGERS = gql(
    """
    query FetchProjectTriggers(
        $projectName: String!,
        $entityName: String!,
    ) {
        project(
            name: $projectName,
            entityName: $entityName,
        ) {
            triggers {
                id
                name
                enabled
                createdAt
                createdBy {id username}
                description
                scope {
                    __typename
                    ... on Project {
                        id
                        name
                    }
                    ... on ArtifactSequence {
                        id
                        name
                    }
                    ... on ArtifactPortfolio {
                        id
                        name
                    }
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
                        queue {
                            __typename
                            id
                            name
                        }
                        template
                    }
                    ... on NotificationTriggeredAction {
                        integration {
                            __typename
                            id
                        }
                        title
                        message
                        severity
                    }
                    ... on GenericWebhookTriggeredAction {
                        integration {
                            __typename
                            ... on GenericWebhookIntegration {
                                id
                                name
                                urlEndpoint
                                accessTokenRef
                                secretRef
                                createdAt
                            }
                        }
                        requestPayload
                    }
                }
            }
        }
    }
    """
)

load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")


# ------------------------------------------------------------------------------
class User(Base):
    id: Base64Id
    username: str


# Scopes
class ArtifactCollectionScope(Base):
    typename__: Literal["ArtifactPortfolio"] = Field(repr=False, alias="__typename")
    id: Base64Id
    name: str


class ProjectScope(Base):
    typename__: Literal["Project"] = Field(repr=False, alias="__typename")
    id: Base64Id
    name: str


class EntityScope(Base):
    typename__: Literal["Entity"] = Field(repr=False, alias="__typename")
    id: Base64Id
    name: str


class Automation(Base):
    """A defined W&B automation."""

    id: Base64Id
    name: str
    description: str | None

    created_at: datetime
    created_by: User

    scope: ArtifactCollectionScope | ProjectScope | EntityScope

    event: AnyEvent
    action: AnyAction

    enabled: bool


class NewAutomation(Base):
    """A newly defined automation, to be prepared and sent by the client to the server."""

    name: str
    description: str | None

    scope: ArtifactCollectionScope | ProjectScope | EntityScope

    event: AnyEvent
    action: AnyAction

    enabled: bool = True


AutomationsAdapter = TypeAdapter(list[Automation])


def get_automations(
    entities: Iterable[str] | str | None = "wandb_Y72QKAKNEFI3G",
    projects: Iterable[str] | str | None = "wandb-registry-model",
    # entities: Iterable[str] | str | None = None,
    # projects: Iterable[str] | str | None = None,
) -> Iterator[Automation]:
    api = _get_api()

    if (entities is None) and (projects is None):
        all_orgs = get_orgs_info()
        entity_project_pairs = iter_entity_project_pairs(all_orgs)
    elif (entities is not None) and (projects is not None):
        entity_project_pairs = product(
            always_iterable(entities), always_iterable(projects)
        )
    else:
        raise NotImplementedError(
            "Filtering on specific entity or project names not yet implemented"
        )

    for entity, project in tqdm(
        entity_project_pairs,
        desc="Fetching automations from entity-project pairs",
    ):
        params = {"entityName": entity, "projectName": project}
        data = api.client.execute(_FETCH_PROJECT_TRIGGERS, variable_values=params)
        yield from AutomationsAdapter.validate_python(data["project"]["triggers"])


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
) -> NewAutomation:
    if event_and_action is not None:
        event, action = event_and_action

    return NewAutomation(
        name=name,
        description=description,
        event=event,
        action=action,
        enabled=enabled,
    )
