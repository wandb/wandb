from __future__ import annotations

from contextlib import contextmanager
from functools import singledispatch
from itertools import chain
from typing import Any, Iterator

import httpx
from pydantic import TypeAdapter

import wandb
from wandb import Api
from wandb.sdk.automations._generated import client as gen_client
from wandb.sdk.automations._generated.enums import (
    EventTriggeringConditionType,
    TriggeredActionType,
    TriggerScopeType,
)
from wandb.sdk.automations._generated.exceptions import GraphQLClientHttpError
from wandb.sdk.automations._generated.fragments import (
    DeleteTriggerResult,
    SlackIntegration,
)
from wandb.sdk.automations._generated.inputs import (
    CreateFilterTriggerInput,
    TriggeredActionConfig,
)
from wandb.sdk.automations._utils import jsonify
from wandb.sdk.automations.actions import NewNotification, NewQueueJob, NewWebhook
from wandb.sdk.automations.automations import AnyNewAction, Automation, NewAutomation
from wandb.sdk.automations.events import NewEventAndAction


@contextmanager
# def _gql_client() -> Iterator[Client]:
def _gql_client() -> Iterator[gen_client.Client]:
    wandb_client = Api().client._client
    url = wandb_client.transport.url
    headers = wandb_client.transport.headers
    sess = wandb_client.transport.session

    http_client = httpx.Client(
        headers=sess.headers, auth=sess.auth, cookies=sess.cookies
    )
    with gen_client.Client(url=url, headers=headers, http_client=http_client) as client:
        yield client


_AutomationsListAdapter = TypeAdapter(list[Automation])


def get_one(
    *,
    name: str | None = None,
    event: str | EventTriggeringConditionType | None = None,
    action: str | TriggeredActionType | None = None,
    scope: str | TriggerScopeType | None = None,
    user: str | None = None,
) -> Automation:
    """Return the only Automation matching the given parameters, if possible.

    Raises:
        ValueError: If 0 or multiple Automations match the search criteria
    """
    params = locals()
    set_params = {k: v for k, v in params.items() if (v is not None)}
    matches = get_all(name=name, event=event, action=action, scope=scope, user=user)

    try:
        [only_match] = matches
    except ValueError:
        if matches:
            raise RuntimeError(
                f"Found multiple ({len(matches)}) automations matching: {set_params!r}"
            )
        else:
            raise RuntimeError(f"No automation found matching: {set_params!r}")
    else:
        return only_match


def get_all(
    *,
    name: str | None = None,
    event: str | EventTriggeringConditionType | None = None,
    action: str | TriggeredActionType | None = None,
    scope: str | TriggerScopeType | None = None,
    user: str | None = None,
) -> list[Automation]:
    """Yield from all Automations matching the givne search criteria."""
    scope_type = None if (scope is None) else TriggerScopeType(scope)
    event_type = None if (event is None) else EventTriggeringConditionType(event)
    action_type = None if (action is None) else TriggeredActionType(action)

    def _should_keep(automation: Automation) -> bool:
        return (
            ((name is None) or (automation.name == name))
            and ((user is None) or (automation.created_by.username == user))
            and ((scope_type is None) or (automation.scope.scope_type is scope_type))
            and ((event_type is None) or (automation.event.event_type is event_type))
            and (
                (action_type is None) or (automation.action.action_type is action_type)
            )
        )

    with _gql_client() as client:
        result = client.triggers_in_user_orgs(entity_name=None)
        entities = chain.from_iterable(
            [org.org_entity, *org.teams] for org in result.organizations
        )
        edges = chain.from_iterable(ent.projects.edges for ent in entities)
        projects = (edge.node for edge in edges)
        triggers = chain.from_iterable(proj.triggers for proj in projects)
        automations = (
            Automation.model_validate(obj.model_dump(exclude={"typename__"}))
            for obj in triggers
        )
        return list(filter(_should_keep, automations))


def create(
    automation_or_pair: NewAutomation | NewEventAndAction,
    *,
    name: str | None = None,
    description: str | None = None,
    enabled: bool = True,
) -> Automation:
    if isinstance(automation_or_pair, NewAutomation):
        automation = automation_or_pair
    elif isinstance(automation_or_pair, tuple):
        event_and_action = automation_or_pair
        automation = define(
            event_and_action,
            name=name or "",
            description=description,
            enabled=enabled,
        )
    else:
        raise TypeError(
            f"Unable to prepare type {type(automation_or_pair).__qualname__!r} into new automation"
        )

    with _gql_client() as client:
        params = CreateFilterTriggerInput(
            name=automation.name,
            description=automation.description,
            enabled=automation.enabled,
            client_mutation_id=automation.client_mutation_id,
            # ------------------------------------------------------------------------------
            scope_type=automation.scope.scope_type,
            scope_id=automation.scope.id,
            # ------------------------------------------------------------------------------
            triggering_event_type=automation.event.event_type,
            event_filter=jsonify(automation.event.filter),
            # ------------------------------------------------------------------------------
            triggered_action_type=automation.action.action_type,
            triggered_action_config=_to_triggered_action_config(automation.action),
        )

        try:
            result = client.create_trigger(
                params=params,
                # name=args.name,
                # triggering_event_type=args.triggering_event_type,
                # scope_type=args.scope_type,
                # scope_id=args.scope_id,
                # event_filter=args.event_filter,
                # triggered_action_type=args.triggered_action_type,
                # triggered_action_config=args.triggered_action_config,
                # enabled=args.enabled,
                # description=args.description,
            )
        except GraphQLClientHttpError as e:
            if e.response.status_code == 409:  # Conflict
                wandb.termlog(
                    f"An automation named {automation.name!r} already exists.  Skipping creation..."
                )
                return get_one(name=name)
            else:
                wandb.termerror(
                    f"Got response status {e.response.status_code!r}: {e.response.text!r}"
                )
                raise e
        return Automation.model_validate(result.trigger)


@singledispatch
def _to_triggered_action_config(action: AnyNewAction) -> TriggeredActionConfig:
    """Return a `TriggeredActionConfig` as required in the input schema of CreateFilterTriggerInput."""
    raise TypeError(
        f"Unsupported action type {type(action).__qualname__!r}: {action!r}"
    )


@_to_triggered_action_config.register
def _(action: NewQueueJob) -> TriggeredActionConfig:
    return TriggeredActionConfig.model_validate(
        dict(queue_job_action_input=action.model_dump())
    )


@_to_triggered_action_config.register
def _(action: NewNotification) -> TriggeredActionConfig:
    return TriggeredActionConfig.model_validate(
        dict(notification_action_input=action.model_dump())
    )


@_to_triggered_action_config.register
def _(action: NewWebhook) -> TriggeredActionConfig:
    return TriggeredActionConfig.model_validate(
        dict(generic_webhook_action_input=action.model_dump())
    )


def copy(automation: Automation, *, name: str, **updates: Any) -> Automation:
    raise NotImplementedError


def define(
    event_and_action: NewEventAndAction,
    *,
    name: str,
    description: str | None = None,
    enabled: bool = True,
) -> NewAutomation:
    event, action = event_and_action
    new_automation = NewAutomation.model_validate(
        dict(
            name=name,
            description=description,
            enabled=enabled,
            scope=event.scope,
            event=event,
            action=action,
        )
    )
    return new_automation


def user_slack_integration() -> SlackIntegration:
    """Get the user's own personal W&B Slack integration."""
    with _gql_client() as client:
        result = client.slack_integrations_for_user()
        try:
            edges = result.integrations.edges
        except AttributeError:
            raise ValueError(
                f"Unable to parse Slack integrations for user from response: {result!r}"
            )
        else:
            # Dump and revalidate to ensure the correct pydantic type names
            nodes = (edge.node for edge in edges)
            integrations = [
                SlackIntegration.model_validate(node.model_dump()) for node in nodes
            ]

        try:
            [only_integration] = integrations
        except ValueError:
            if integrations:
                raise RuntimeError(
                    f"Found multiple ({len(integrations)}) Slack integrations: {integrations!r}"
                )
            else:
                raise RuntimeError(
                    "No slack integration found!  You can set one up for your W&B user at: https://wandb.ai/settings"
                )
        else:
            return only_integration


def team_slack_integration(entity: str | None = None) -> SlackIntegration:
    """Get the Slack integration for an entity, if given, or the user's default entity."""
    with _gql_client() as client:
        result = client.slack_integrations_for_team(entity_name=entity)
        try:
            edges = result.integrations.edges
        except AttributeError:
            raise ValueError(
                f"Unable to parse Slack integrations for entity {entity!r} from response: {result!r}"
            )
        else:
            # Dump and revalidate to ensure the correct pydantic type names
            nodes = (edge.node for edge in edges)
            integrations = [
                SlackIntegration.model_validate(node.model_dump()) for node in nodes
            ]

        try:
            [only_integration] = integrations
        except ValueError:
            if integrations:
                raise RuntimeError(
                    f"Found multiple ({len(integrations)}) Slack integrations for team {entity!r}: {integrations!r}"
                )
            else:
                raise RuntimeError(
                    f"No slack integration found!  A team admin for {entity!r} can set one up at: https://wandb.ai/{entity}/settings"
                )
        else:
            return only_integration


def delete(obj: str | Automation) -> DeleteTriggerResult:
    with _gql_client() as client:
        match obj:
            case Automation(id=id_):
                params = {"id": id_}
            case str() as id_:
                params = {"id": id_}
            case _:
                raise TypeError(
                    f"Unable to parse automation ID from type: {type(obj).__qualname__!r}"
                )

        result = client.delete_trigger(id=params["id"])
        try:
            obj_dict = result.model_dump()
        except AttributeError:
            raise ValueError(f"Unable to parse deleted trigger response: {result!r}")
        else:
            return DeleteTriggerResult.model_validate(obj_dict)
