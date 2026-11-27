from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from pytest import FixtureRequest, fixture, mark, raises
from wandb.automations import (
    ActionType,
    ArtifactEvent,
    EventType,
    NewAutomation,
    OnAddArtifactAlias,
    OnAddArtifactTag,
    OnAddCollectionTag,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRemoveArtifactTag,
    OnRemoveCollectionTag,
    OnRunMetric,
    OnUnlinkArtifact,
    RegistryScope,
    RunEvent,
    ScopeType,
)
from wandb.automations._inputs import (
    INVALID_INPUT_ACTIONS,
    INVALID_INPUT_EVENTS,
    prepare_to_create,
    prepare_to_update,
)
from wandb.automations.actions import InputAction, SavedNoOpAction
from wandb.automations.automations import Automation
from wandb.automations.events import InputEvent, OnRunState

from ._cases import (
    invalid_events_and_scopes,
    valid_input_actions,
    valid_input_events,
    valid_scopes,
)


class TestPrepareToCreate:
    """Checks on the internal helper that prepares the GraphQL input for CreateFilterTrigger mutations."""

    # Payload components are independent. Individual tests opt into only the
    # axes they assert on, instead of inheriting the full fixture product.
    @fixture
    def scope_type(self, request):
        return getattr(request, "param", ScopeType.PROJECT)

    @fixture
    def event_type(self, request):
        return getattr(request, "param", EventType.LINK_ARTIFACT)

    @fixture
    def action_type(self, request):
        return getattr(request, "param", ActionType.NO_OP)

    def test_same_results_from_equivalent_args(self, input_event, input_action):
        """Check that preparing the CreateFilterTrigger input object by passing the same values in different ways produces identical results."""
        name = "test-name"
        description = "test-description"
        enabled = True

        attrs = dict(name=name, description=description, enabled=enabled)

        # REFERENCE: via NewAutomation instance as only positional arg
        expected_gql_input = prepare_to_create(
            NewAutomation(event=input_event, action=input_action, **attrs)
        )

        # ------------------------------------------------------------------------------
        # via only keyword args
        gql_input_via_kws = prepare_to_create(
            event=input_event, action=input_action, **attrs
        )

        assert expected_gql_input == gql_input_via_kws

        # ------------------------------------------------------------------------------
        # via `event >> action` and keyword args
        gql_input_via_event_action_and_kws = prepare_to_create(
            input_event >> input_action,
            **attrs,
        )

        assert expected_gql_input == gql_input_via_event_action_and_kws

        # ------------------------------------------------------------------------------
        # via NewAutomation instance and keyword args as overrides

        # Orig values deliberately different to check that they're overridden
        orig_obj = NewAutomation(
            event=input_event,
            action=input_action,
            name=f"REPLACED-{name}",
            description=f"REPLACED-{description}",
            enabled=not enabled,
        )
        gql_input_via_obj_and_kwargs = prepare_to_create(orig_obj, **attrs)

        assert expected_gql_input == gql_input_via_obj_and_kwargs

    def test_registry_scoped_artifact_event(self, registry, do_nothing):
        event = OnLinkArtifact(
            scope=registry,
            filter=ArtifactEvent.alias == "prod",
        )

        assert isinstance(event.scope, RegistryScope)
        assert event.scope.is_registry is True

        prepared = prepare_to_create(event >> do_nothing, name="test-automation")
        prepared_vars = prepared.model_dump()
        assert prepared_vars["scopeType"] == ScopeType.PROJECT.value
        assert prepared_vars["scopeID"] == registry.id

    @mark.parametrize("invalid_event_type", INVALID_INPUT_EVENTS)
    def test_input_event_rejects_legacy_type_assignment(
        self,
        input_event,
        invalid_event_type,
    ):
        with raises(ValidationError, match="event_type"):
            input_event.event_type = invalid_event_type

    @mark.parametrize("invalid_action_type", INVALID_INPUT_ACTIONS)
    def test_input_action_type_is_immutable(
        self,
        input_action,
        invalid_action_type,
    ):
        with raises(ValidationError, match="frozen"):
            input_action.action_type = invalid_action_type

    @fixture
    def input_kwargs(self, request: FixtureRequest) -> dict[str, Any]:
        return getattr(request, "param", {"name": "test-name"})

    @fixture
    def prepared_vars(
        self,
        input_event: InputEvent,
        input_action: InputAction,
        input_kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        # If we were to actually send this new Automation to the server,
        # these the input variables for the GraphQL mutation.
        prepared = prepare_to_create(input_event >> input_action, **input_kwargs)
        return prepared.model_dump()

    @mark.parametrize(
        "input_kwargs",
        [
            {"name": "test-name", "description": "test-description", "enabled": True},
            {"name": "test-name", "enabled": False},
            {"name": "test-name"},
        ],
        indirect=True,
        ids=["explicit", "disabled", "defaults"],
    )
    def test_prepared_dict_values(
        self,
        scope,
        scope_type,
        event_type,
        action_type,
        input_kwargs,
        prepared_vars,
    ):
        """Check that preparing the GraphQL variables for creating a new Automation exports GraphQL variables with the expected keys and values."""
        # This only checks the simpler key-value pairs (without nested payloads).
        # We've omitted the more complicated event/action payloads, which will be checked separately.
        expected_subset = {
            "scopeType": scope_type,
            "scopeID": scope.id,
            "triggeringEventType": event_type,
            "triggeredActionType": action_type,
            **input_kwargs,
        }
        # Expected defaults, if they weren't provided
        if "enabled" not in input_kwargs:
            expected_subset["enabled"] = True

        assert expected_subset.keys() <= prepared_vars.keys()
        for k, expected_val in expected_subset.items():
            prepared_val = prepared_vars[k]
            assert prepared_val == expected_val

        # Check all expected keys are present
        other_expected_keys = {"eventFilter", "triggeredActionConfig"}
        assert {*expected_subset.keys(), *other_expected_keys} == prepared_vars.keys()

    @mark.parametrize(
        ("event_type", "scope_type"),
        [
            (event, scope)
            for event in valid_input_events()
            for scope in valid_scopes()
            if (event, scope) not in invalid_events_and_scopes()
        ],
        indirect=True,
    )
    def test_event_identity_and_scope(
        self, prepared_vars, event_type, scope_type, scope
    ):
        assert prepared_vars["triggeringEventType"] == event_type
        assert prepared_vars["scopeType"] == scope_type
        assert prepared_vars["scopeID"] == scope.id

    @mark.parametrize("action_type", valid_input_actions(), indirect=True)
    def test_action_identity(self, prepared_vars, action_type):
        assert prepared_vars["triggeredActionType"] == action_type

    # ----------------------------------------------------------------------------
    # Check prepared event payloads
    @fixture
    def event_filter_dict(self, prepared_vars) -> dict[str, Any]:
        """The prepared and DESERIALIZED `CreateFilterTriggerInput.eventFilter` payload."""
        return json.loads(prepared_vars["eventFilter"])

    @mark.parametrize("event_type", [EventType.RUN_METRIC_THRESHOLD], indirect=True)
    def test_event_payload_for_run_metric_threshold_events(
        self, input_event, event_filter_dict
    ):
        # Check the run filter
        orig_run_filter = input_event.filter.run
        run_filter_dict = json.loads(event_filter_dict["run_filter"])

        # Check that the filter is nested/wrapped as required by current backend/frontend logic
        assert run_filter_dict == orig_run_filter.model_dump()

        # Check the metric threshold condition
        orig_threshold_filter = input_event.filter.metric.threshold_filter
        threshold_dict = event_filter_dict["run_metric_filter"]["threshold_filter"]
        assert threshold_dict == {
            "agg_op": orig_threshold_filter.agg,
            "cmp_op": orig_threshold_filter.cmp,
            "threshold": orig_threshold_filter.threshold,
            "name": orig_threshold_filter.name,
            "window_size": orig_threshold_filter.window,
        }

    @mark.parametrize(
        "event_type",
        [
            EventType.CREATE_ARTIFACT,
            EventType.ADD_ARTIFACT_ALIAS,
            EventType.ADD_ARTIFACT_TAG,
            EventType.ADD_COLLECTION_TAG,
            EventType.LINK_ARTIFACT,
            EventType.REMOVE_ARTIFACT_TAG,
            EventType.REMOVE_COLLECTION_TAG,
            EventType.UNLINK_ARTIFACT,
        ],
        indirect=True,
    )
    @mark.parametrize("scope_type", [ScopeType.ARTIFACT_COLLECTION], indirect=True)
    def test_event_payload_for_artifact_mutation_events(
        self, input_event, event_filter_dict, scope_type
    ):
        # Check that the filter is nested/wrapped as required by current backend/frontend logic
        #
        # Besides that, check the event payload: event filter should
        # otherwise match what was set on the event instance.
        assert event_filter_dict == input_event.filter.model_dump()

        # Current frontend logic needs these event filters to be wrapped like:
        #     {"$or": [{"$and": [...]}]}
        assert event_filter_dict.keys() == {"$or"}
        assert len(event_filter_dict["$or"]) == 1
        assert event_filter_dict["$or"][0].keys() == {"$and"}

    @mark.parametrize("event_type", [EventType.RUN_STATE], indirect=True)
    def test_event_payload_for_run_state_events(self, event_filter_dict):
        assert json.loads(event_filter_dict["run_filter"]) == {
            "$and": [{"display_name": {"$contains": "my-run"}}]
        }
        assert event_filter_dict["run_state_filter"] == {"states": ["FAILED"]}

    # ----------------------------------------------------------------------------
    # Check prepared action payloads
    @fixture
    def action_config_dict(self, prepared_vars) -> dict[str, Any]:
        """The prepared `CreateFilterTriggerInput.triggeredActionConfig` payload."""
        return prepared_vars["triggeredActionConfig"]

    @mark.parametrize("action_type", [ActionType.NO_OP], indirect=True)
    def test_action_payload_for_no_op_actions(self, action_config_dict):
        assert action_config_dict == {"noOpActionInput": {"noOp": True}}

    @mark.parametrize("action_type", [ActionType.NOTIFICATION], indirect=True)
    def test_action_payload_for_notification_actions(
        self, input_action, action_config_dict
    ):
        assert action_config_dict == {
            "notificationActionInput": {
                "integrationID": input_action.integration_id,
                "title": input_action.title,
                "message": input_action.message,
                "severity": input_action.severity,
            },
        }

    @mark.parametrize("action_type", [ActionType.GENERIC_WEBHOOK], indirect=True)
    def test_action_payload_for_webhook_actions(self, input_action, action_config_dict):
        assert action_config_dict == {
            "genericWebhookActionInput": {
                "integrationID": input_action.integration_id,
                "requestPayload": json.dumps(
                    input_action.request_payload, separators=(",", ":")
                ),
            },
        }

    @mark.parametrize("action_type", [ActionType.ARIA], indirect=True)
    def test_action_payload_for_aria_actions(self, input_action, action_config_dict):
        assert action_config_dict == {
            "ariaActionInput": {"prompt": input_action.prompt},
        }


class TestPrepareToUpdate:
    """Checks on the internal helper that prepares the GraphQL input for UpdateFilterTrigger mutations."""

    @fixture
    def saved_action(self):
        return SavedNoOpAction()

    MUTATION_EVENT_CLASSES: dict[EventType, type[InputEvent]] = {
        EventType.CREATE_ARTIFACT: OnCreateArtifact,
        EventType.ADD_ARTIFACT_ALIAS: OnAddArtifactAlias,
        EventType.LINK_ARTIFACT: OnLinkArtifact,
        EventType.UNLINK_ARTIFACT: OnUnlinkArtifact,
        EventType.ADD_ARTIFACT_TAG: OnAddArtifactTag,
        EventType.REMOVE_ARTIFACT_TAG: OnRemoveArtifactTag,
        EventType.ADD_COLLECTION_TAG: OnAddCollectionTag,
        EventType.REMOVE_COLLECTION_TAG: OnRemoveCollectionTag,
    }

    def test_update_event_preserves_mutation_filter(
        self,
        saved_automation: Automation,
        mutation_event_type: EventType,
        artifact_collection,
    ):
        """Updating an automation with a new InputEvent must preserve the event filter."""
        event_cls = self.MUTATION_EVENT_CLASSES[mutation_event_type]
        new_event = event_cls(
            scope=artifact_collection,
            filter=ArtifactEvent.alias == "prod",
        )

        result = prepare_to_update(saved_automation, event=new_event)
        event_filter = json.loads(result.event_filter)

        assert event_filter != {"$and": []}
        assert event_filter == {"$or": [{"$and": [{"alias": {"$eq": "prod"}}]}]}

    def test_update_without_event_preserves_existing_filter(
        self,
        saved_automation: Automation,
    ):
        """Calling prepare_to_update with no event kwarg must preserve the original filter."""
        result = prepare_to_update(saved_automation)
        event_filter = json.loads(result.event_filter)

        assert event_filter != {"$and": []}
        assert event_filter == {"$or": [{"$and": [{"alias": {"$eq": "latest"}}]}]}

    def test_update_name_only_preserves_filter(
        self,
        saved_automation: Automation,
    ):
        """Updating only the name must not alter the event filter."""
        result = prepare_to_update(saved_automation, name="new-name")
        event_filter = json.loads(result.event_filter)

        assert result.name == "new-name"
        assert event_filter != {"$and": []}
        assert event_filter == {"$or": [{"$and": [{"alias": {"$eq": "latest"}}]}]}

    # --------------------------------------------------------------------------
    # Run-event update coverage

    RUN_EVENT_FACTORIES = {
        EventType.RUN_METRIC_THRESHOLD: lambda scope: OnRunMetric(
            scope=scope,
            filter=RunEvent.metric("my-metric").avg(5).gt(0),
        ),
        EventType.RUN_METRIC_CHANGE: lambda scope: OnRunMetric(
            scope=scope,
            filter=RunEvent.metric("my-metric").avg(5).increases_by(diff=123.45),
        ),
        EventType.RUN_METRIC_ZSCORE: lambda scope: OnRunMetric(
            scope=scope,
            filter=RunEvent.metric("my-metric").zscore(5).gt(3),
        ),
        EventType.RUN_STATE: lambda scope: OnRunState(
            scope=scope,
            filter=RunEvent.state == "failed",
        ),
    }

    @mark.parametrize(
        "run_event_type",
        sorted(RUN_EVENT_FACTORIES.keys()),
        indirect=True,
        ids=lambda x: f"event={x.value}",
    )
    def test_update_run_event_preserves_filter(
        self,
        saved_run_automation: Automation,
        run_event_type: EventType,
        project,
    ):
        """Updating an automation with a new run InputEvent must serialize correctly."""
        factory = self.RUN_EVENT_FACTORIES[run_event_type]
        new_event = factory(project)

        result = prepare_to_update(saved_run_automation, event=new_event)
        event_filter = json.loads(result.event_filter)

        assert event_filter == new_event.filter.model_dump()
        assert result.triggering_event_type == new_event.event_type


class TestSavedActionInput:
    @fixture
    def mutation_event_type(self):
        return EventType.LINK_ARTIFACT

    def test_update_preserves_saved_action(self, saved_automation, saved_action):
        expected = {
            ActionType.NO_OP: {"noOpActionInput": {"noOp": True}},
            ActionType.NOTIFICATION: {
                "notificationActionInput": {
                    "integrationID": "PLACEHOLDER",
                    "title": "",
                    "message": "",
                    "severity": "INFO",
                }
            },
            ActionType.GENERIC_WEBHOOK: {
                "genericWebhookActionInput": {"integrationID": "PLACEHOLDER"}
            },
            ActionType.ARIA: {"ariaActionInput": {"prompt": "Summarize this run"}},
        }
        result = prepare_to_update(saved_automation)
        assert (
            result.triggered_action_config.model_dump()
            == expected[saved_action.action_type]
        )
