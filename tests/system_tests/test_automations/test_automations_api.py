from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Generator
from itertools import islice
from typing import Any

import wandb
from pytest import FixtureRequest, fixture, mark, raises, skip
from wandb.apis.public import ArtifactCollection, Project, Registry
from wandb.automations import (
    ActionType,
    ArtifactEvent,
    Automation,
    DoNothing,
    EventType,
    MetricChangeFilter,
    MetricThresholdFilter,
    MetricZScoreFilter,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    OnRunState,
    ProjectScope,
    RegistryScope,
    RunEvent,
    ScopeType,
    SendWebhook,
    WebhookIntegration,
)
from wandb.automations._run_metric_filters import ChangeDir
from wandb.automations._run_state_filters import ReportedRunState, StateFilter
from wandb.automations.actions import InputAction, SavedNoOpAction, SavedWebhookAction
from wandb.automations.events import InputEvent, RunMetricFilter, RunStateFilter
from wandb.errors.errors import CommError


@fixture
def automation_name(make_name: Callable[[str], str]) -> str:
    return make_name(prefix="test-automation")


@fixture
def reset_automations(module_api: wandb.Api):
    """Request this fixture to clear any existing automations before a test."""
    # There has to be a better way to do this
    for automation in module_api.automations():
        module_api.delete_automation(automation)
    yield


# ------------------------------------------------------------------------------
@mark.usefixtures(reset_automations.__name__)
def test_no_initial_automations(module_api: wandb.Api):
    """No automations should be fetched by the API prior to creating any."""
    assert list(module_api.automations()) == []


def test_no_initial_integrations(module_api: wandb.Api):
    """No automations should be fetched by the API prior to creating any."""
    assert list(module_api.integrations()) == []
    assert list(module_api.slack_integrations()) == []
    assert list(module_api.webhook_integrations()) == []


def test_fetch_webhook_integrations(
    module_api: wandb.Api,
    make_name,
    make_webhook_integration,
):
    """Test fetching webhook integrations."""
    # Create multiple webhook integrations
    created_hooks = [
        make_webhook_integration(
            name=make_name("test-webhook"),
            entity=module_api.default_entity,
            url="https://example.com/webhook",
        )
        for _ in range(3)
    ]
    created_hooks_by_name = {wh.name: wh for wh in created_hooks}

    fetched_hooks = list(
        module_api.webhook_integrations(entity=module_api.default_entity)
    )
    filtered_hooks = [wh for wh in fetched_hooks if wh.name in created_hooks_by_name]

    assert len(filtered_hooks) == len(created_hooks)

    for fetched_hook in filtered_hooks:
        orig_hook = created_hooks_by_name[fetched_hook.name]

        assert orig_hook.name == fetched_hook.name
        assert orig_hook.url_endpoint == fetched_hook.url_endpoint


def test_fetch_slack_integrations(
    module_api: wandb.Api,
    make_name,
    make_webhook_integration,
):
    """Test fetching slack integrations."""
    # We don't currently have an easy way of creating real Slack integrations in the backend
    # for system tests, but at least test that the API call doesn't error out.

    # Create a webhook integration only to check that it's omitted from slack_integrations()
    make_webhook_integration(
        name=make_name("test-webhook"),
        entity=module_api.default_entity,
        url="https://example.com/webhook",
    )

    # Fetch the slack integrations (for now there won't be any)
    fetched_slack_integrations = list(
        module_api.slack_integrations(entity=module_api.default_entity)
    )
    assert len(fetched_slack_integrations) == 0


@mark.usefixtures(reset_automations.__name__)
def test_create_automation(
    module_user: str,
    module_api: wandb.Api,
    event,
    action,
    automation_name: str,
):
    created = module_api.create_automation(
        (event >> action), name=automation_name, description="test description"
    )

    # We should be able to fetch the automation by name (optionally filtering by entity)
    assert created.name == automation_name

    fetched_a = module_api.automation(
        entity=module_user,
        name=created.name,
    )
    fetched_b = module_api.automation(name=created.name)

    assert fetched_a == created
    assert fetched_b == created


@mark.usefixtures(reset_automations.__name__)
def test_create_existing_automation_raises_by_default_if_existing(
    module_api: wandb.Api,
    event,
    action,
    automation_name: str,
):
    created = module_api.create_automation(
        (event >> action),
        name=automation_name,
    )
    with raises(CommError):
        module_api.create_automation((event >> action), name=created.name)

    # Fetching the automation by name should return the original automation, unchanged.
    fetched = module_api.automation(name=created.name)
    assert fetched == created


@mark.usefixtures(reset_automations.__name__)
def test_create_existing_automation_fetches_existing_if_requested(
    module_api: wandb.Api,
    event,
    action,
    automation_name: str,
):
    created = module_api.create_automation(
        (event >> action),
        name=automation_name,
    )

    # Since we request the prior automation if it exists, any extra values
    # that would normally be set on the created object will be ignored.
    existing = module_api.create_automation(
        (event >> action),
        name=created.name,
        description="ignored description",
        fetch_existing=True,
    )

    # Fetch the automation by name
    fetched = module_api.automation(name=created.name)

    assert created == existing
    assert existing == fetched

    assert created.description is None
    assert existing.description is None
    assert fetched.description is None


@mark.usefixtures(reset_automations.__name__)
def test_create_automation_for_run_metric_threshold_event(
    project,
    webhook,
    module_api: wandb.Api,
    automation_name: str,
):
    """Check that creating an automation for the `RUN_METRIC_THRESHOLD` event works, and the automation is saved with the expected filter."""
    metric_name = "my-metric"
    run_name = "my-run"
    window = 5
    threshold = 0

    expected_filter = RunMetricFilter(
        run={
            "$and": [{"display_name": {"$contains": run_name}}],
        },
        metric=MetricThresholdFilter(
            name=metric_name,
            window=window,
            agg="AVERAGE",
            cmp="$gt",
            threshold=threshold,
        ),
    )

    event = OnRunMetric(
        scope=project,
        filter=(
            RunEvent.metric(metric_name).mean(window).gt(threshold)
            & RunEvent.name.contains(run_name)
        ),
    )
    action = SendWebhook.from_integration(
        webhook,
        payload={"test": {"key": "value"}},
    )

    server_supports_event = module_api._supports_automation(
        event=event.event_type,
    )

    if not server_supports_event:
        with raises(CommError):
            module_api.create_automation(
                (event >> action),
                name=automation_name,
                description="test description",
            )

    else:
        # The server supports the event, so there should be an automation to check
        created = module_api.create_automation(
            (event >> action),
            name=automation_name,
            description="test description",
        )
        assert isinstance(created, Automation)
        assert created.event.filter == expected_filter

        # Refetch it to be sure
        refetched = module_api.automation(name=automation_name)
        assert isinstance(refetched, Automation)
        assert refetched.event.filter == expected_filter
        assert refetched.action.request_payload == {"test": {"key": "value"}}


@mark.usefixtures(reset_automations.__name__)
def test_create_automation_for_run_metric_change_event(
    project,
    webhook,
    module_api: wandb.Api,
    automation_name: str,
):
    """Check that creating an automation for the `RUN_METRIC_CHANGE` event works, and the automation is saved with the expected filter."""
    metric_name = "my-metric"
    run_name = "my-run"
    window = 5
    amount = 0.5

    expected_filter = RunMetricFilter(
        run={
            "$and": [{"display_name": {"$contains": run_name}}],
        },
        metric=MetricChangeFilter(
            name=metric_name,
            window=window,
            prior_window=window,
            agg="AVERAGE",
            change_dir="ANY",
            change_type="RELATIVE",
            threshold=amount,
        ),
    )

    event = OnRunMetric(
        scope=project,
        filter=(
            RunEvent.metric(metric_name).avg(window).changes_by(frac=amount)
            & RunEvent.name.contains(run_name)
        ),
    )
    action = SendWebhook.from_integration(webhook)

    server_supports_event = module_api._supports_automation(
        event=event.event_type,
    )

    if not server_supports_event:
        with raises(CommError):
            module_api.create_automation(
                (event >> action),
                name=automation_name,
                description="test description",
            )
    else:
        # The server supports the event, so there should be an automation to check
        created = module_api.create_automation(
            (event >> action),
            name=automation_name,
            description="test description",
        )
        assert isinstance(created, Automation)
        assert created.event.filter == expected_filter

        # Refetch it to be sure
        refetched = module_api.automation(name=automation_name)
        assert isinstance(refetched, Automation)
        assert refetched.event.filter == expected_filter


@mark.usefixtures(reset_automations.__name__)
def test_create_automation_for_run_state_event(
    project,
    webhook,
    module_api: wandb.Api,
    automation_name: str,
):
    """Check that creating an automation for the `RUN_STATE` event works, and the automation is saved with the expected filter."""
    run_name = "my-run"
    state = ReportedRunState.FAILED

    expected_filter = RunStateFilter(
        run={
            "$and": [{"display_name": {"$contains": run_name}}],
        },
        state=StateFilter(states=[state]),
    )

    event = OnRunState(
        scope=project,
        filter=RunEvent.name.contains(run_name) & RunEvent.state.eq(state),
    )
    action = SendWebhook.from_integration(webhook)

    server_supports_event = module_api._supports_automation(
        event=event.event_type,
    )

    if not server_supports_event:
        with raises(CommError):
            module_api.create_automation(
                (event >> action),
                name=automation_name,
                description="test description",
            )
    else:
        # The server supports the event, so there should be an automation to check
        created = module_api.create_automation(
            (event >> action),
            name=automation_name,
            description="test description",
        )
        assert isinstance(created, Automation)
        assert created.event.filter == expected_filter

        # Refetch it to be sure
        refetched = module_api.automation(name=automation_name)
        assert isinstance(refetched, Automation)
        assert refetched.event.filter == expected_filter


@mark.usefixtures(reset_automations.__name__)
def test_create_automation_for_run_metric_zscore_event(
    project,
    webhook,
    module_api: wandb.Api,
    automation_name: str,
):
    """Check that creating an automation for the `RUN_METRIC_ZSCORE` event works, and the automation is saved with the expected filter."""
    metric_name = "my-metric"
    run_name = "my-run"
    window = 5
    threshold = 2.0

    expected_filter = RunMetricFilter(
        run={
            "$and": [{"display_name": {"$contains": run_name}}],
        },
        metric=MetricZScoreFilter(
            name=metric_name,
            window=window,
            threshold=threshold,
            change_dir=ChangeDir.ANY,
        ),
    )

    event = OnRunMetric(
        scope=project,
        filter=(
            MetricZScoreFilter(
                name=metric_name,
                window=window,
                threshold=threshold,
                change_dir=ChangeDir.ANY,
            )
            & RunEvent.name.contains(run_name)
        ),
    )
    action = SendWebhook.from_integration(webhook)

    server_supports_event = module_api._supports_automation(event=event.event_type)

    if not server_supports_event:
        with raises(CommError):
            module_api.create_automation(
                (event >> action),
                name=automation_name,
                description="test description",
            )
    else:
        # The server supports the event, so there should be an automation to check
        created = module_api.create_automation(
            (event >> action),
            name=automation_name,
            description="test description",
        )
        assert isinstance(created, Automation)
        assert created.event.filter == expected_filter

        # Refetch it to be sure
        refetched = module_api.automation(name=automation_name)
        assert isinstance(refetched, Automation)
        assert refetched.event.filter == expected_filter


@fixture
def created_automation(
    module_api: wandb.Api,
    reset_automations,
    event,
    action,
    automation_name: str,
) -> Automation:
    """An already-created automation that we can use for testing."""
    created = module_api.create_automation(
        (event >> action),
        name=automation_name,
    )

    fetched = module_api.automation(name=created.name)

    assert created.name == fetched.name == automation_name  # Sanity check
    return fetched


def test_delete_automation(
    module_api: wandb.Api, automation_name: str, created_automation: Automation
):
    assert module_api.automation(name=automation_name) == created_automation

    module_api.delete_automation(created_automation)

    # We should no longer be able to fetch the deleted automation
    with raises(ValueError):
        module_api.automation(name=automation_name)


def test_delete_automation_by_id(
    module_api: wandb.Api, automation_name: str, created_automation: Automation
):
    assert module_api.automation(name=automation_name) == created_automation

    module_api.delete_automation(created_automation.id)

    # We should no longer be able to fetch the deleted automation
    with raises(ValueError):
        module_api.automation(name=automation_name)


def test_automation_cannot_be_deleted_again(
    module_api: wandb.Api, automation_name: str, created_automation: Automation
):
    assert module_api.automation(name=automation_name) == created_automation

    module_api.delete_automation(created_automation)

    # We should no longer be able to fetch the deleted automation
    with raises(ValueError):
        module_api.automation(name=automation_name)

    # Deleting the automation again (by object or ID) should raise the same error
    with raises(CommError):
        module_api.delete_automation(created_automation)
    with raises(CommError):
        module_api.delete_automation(created_automation.id)


@mark.usefixtures(reset_automations.__name__)
def test_delete_automation_raises_on_invalid_id(module_api: wandb.Api):
    with raises(CommError):
        module_api.delete_automation("invalid-automation-id")


class TestUpdateAutomation:
    @fixture
    def action_type(self) -> ActionType:
        """Pin the action axis so these tests start from a webhook automation.

        This overrides the parametrized action_type fixture. These update
        behaviors do not depend on the action, so pinning it avoids multiplying
        every case by the number of action types.
        """
        return ActionType.GENERIC_WEBHOOK

    @fixture(scope="class")
    def make_automation(
        self,
        make_module_api: Callable[[], wandb.Api],
        make_name: Callable[[str], str],
    ) -> Generator[Callable[[InputEvent, InputAction], Automation]]:
        """Factory that creates automations to update, cleaned up once per class.

        Each call uses a fresh unique name. These tests only run against servers
        new enough to support editing automations, where the created object can
        be used directly without refetching.
        """
        created: deque[Automation] = deque()

        def _make(event: InputEvent, action: InputAction) -> Automation:
            # A fresh Api per call: the one from a prior test is invalidated by
            # the teardown that runs between tests.
            automation = make_module_api().create_automation(
                (event >> action),
                name=make_name("test-automation"),
                description="orig description",
            )
            created.append(automation)
            return automation

        yield _make

        # No test here deletes automations, but other tests share this user and
        # may reset it, so an automation may already be gone.
        api = make_module_api()
        for automation in created:
            try:
                api.delete_automation(automation)
            except CommError:
                pass

    @fixture
    def old_automation(
        self,
        make_automation: Callable[[InputEvent, InputAction], Automation],
        action: InputAction,
        artifact_collection: ArtifactCollection,
    ) -> Automation:
        """A canonical automation to update.

        Its event, action, and scope are immaterial to most update tests, so we
        fix them here rather than fan out over every combination. Event- and
        scope-varying behaviors are covered by the parametrized tests below.
        """
        old_event = OnLinkArtifact(
            scope=artifact_collection,
            filter=ArtifactEvent.alias.matches_regex("^my-artifact.*"),
        )
        return make_automation(old_event, action)

    def test_update_name(
        self,
        module_api: wandb.Api,
        old_automation: Automation,
        make_name: Callable[[str], str],
    ):
        updated_value = make_name("renamed-automation")

        old_automation.name = updated_value
        new_automation = module_api.update_automation(old_automation)

        assert new_automation.name == updated_value

    def test_update_description(
        self, module_api: wandb.Api, old_automation: Automation
    ):
        new_value = "new description"

        old_automation.description = new_value
        new_automation = module_api.update_automation(old_automation)

        assert new_automation.description == new_value

    def test_update_enabled(self, module_api: wandb.Api, old_automation: Automation):
        new_value = False

        old_automation.enabled = new_value
        new_automation = module_api.update_automation(old_automation)

        assert new_automation.enabled == new_value

    def test_update_action_to_webhook(
        self,
        module_api: wandb.Api,
        old_automation: Automation,
        webhook: WebhookIntegration,
    ):
        # This is deliberately an "input" action, even though saved automations
        # will have a "saved" action on them.  We want to check that this is still
        # handled correctly and reliably.
        webhook_id = webhook.id
        new_payload = {"new-key": "new-value"}
        webhook_action = SendWebhook(
            integration_id=webhook_id,
            request_payload=new_payload,
        )

        old_automation.action = webhook_action
        new_automation = module_api.update_automation(old_automation)

        new_action = new_automation.action
        assert isinstance(new_action, SavedWebhookAction)
        assert new_action.action_type == ActionType.GENERIC_WEBHOOK
        assert new_action.integration.id == webhook_id
        assert new_action.request_payload == new_payload

    def test_update_action_to_no_op(
        self, module_api: wandb.Api, old_automation: Automation
    ):
        # This is deliberately an "input" action, even though saved automations
        # will have a "saved" action on them.  We want to check that this is still
        # handled correctly and reliably.

        old_automation.action = DoNothing()
        new_automation = module_api.update_automation(old_automation)

        new_action = new_automation.action
        # NO_OP actions don't have meaningful fields besides these
        assert isinstance(new_action, SavedNoOpAction)
        assert new_action.action_type == ActionType.NO_OP

    def test_update_webhook_payload(
        self,
        module_api: wandb.Api,
        old_automation: Automation,
    ):
        assert isinstance(old_automation.action, SavedWebhookAction)  # Precondition

        new_payload = {"new-key": "new-value"}
        old_automation.action.request_payload = new_payload
        new_automation = module_api.update_automation(old_automation)

        assert new_automation.action.request_payload == new_payload

    def test_update_scope_to_project(
        self,
        module_api: wandb.Api,
        old_automation: Automation,
        project: Project,
    ):
        old_automation.scope = project

        new_automation = module_api.update_automation(old_automation)
        updated_scope = new_automation.scope

        assert isinstance(updated_scope, ProjectScope)
        assert updated_scope.is_registry is False
        assert updated_scope.id == project.id
        assert updated_scope.name == project.name

    def test_update_scope_to_registry(
        self,
        module_api: wandb.Api,
        old_automation: Automation,
        registry: Registry,
    ):
        old_automation.scope = registry

        new_automation = module_api.update_automation(old_automation)
        updated_scope = new_automation.scope

        assert isinstance(updated_scope, RegistryScope)
        assert updated_scope.is_registry is True
        assert updated_scope.id == registry.id
        assert updated_scope.name == registry.full_name
        assert updated_scope.name.startswith("wandb-registry-")

    # Each mutation event, started on a scope it supports. CREATE_ARTIFACT only
    # supports collection scope, so it starts and stays there. The rest start on
    # a project so the update is a genuine scope transition.
    MUTATION_EVENT_SCOPES = [
        (EventType.ADD_ARTIFACT_ALIAS, ScopeType.PROJECT),
        (EventType.ADD_ARTIFACT_TAG, ScopeType.PROJECT),
        (EventType.ADD_COLLECTION_TAG, ScopeType.PROJECT),
        (EventType.LINK_ARTIFACT, ScopeType.PROJECT),
        (EventType.REMOVE_ARTIFACT_TAG, ScopeType.PROJECT),
        (EventType.REMOVE_COLLECTION_TAG, ScopeType.PROJECT),
        (EventType.UNLINK_ARTIFACT, ScopeType.PROJECT),
        (EventType.CREATE_ARTIFACT, ScopeType.ARTIFACT_COLLECTION),
    ]

    @mark.parametrize(
        ("event_type", "scope_type"),
        MUTATION_EVENT_SCOPES,
        indirect=True,
        ids=lambda v: v.value,
    )
    def test_update_scope_to_artifact_collection(
        self,
        module_api: wandb.Api,
        make_automation: Callable[[InputEvent, InputAction], Automation],
        event: InputEvent,
        action: InputAction,
        event_type: EventType,
        artifact_collection: ArtifactCollection,
    ):
        old_automation = make_automation(event, action)
        assert old_automation.event.event_type == event_type  # Consistency check

        old_automation.scope = artifact_collection
        new_automation = module_api.update_automation(old_automation)

        updated_scope = new_automation.scope

        assert updated_scope.scope_type is ScopeType.ARTIFACT_COLLECTION
        assert updated_scope.id == artifact_collection.id
        assert updated_scope.name == artifact_collection.name

    # Run events only support project scope. Updating one to a collection must fail.
    RUN_EVENT_SCOPES = [
        (EventType.RUN_METRIC_THRESHOLD, ScopeType.PROJECT),
        (EventType.RUN_METRIC_CHANGE, ScopeType.PROJECT),
        (EventType.RUN_METRIC_ZSCORE, ScopeType.PROJECT),
        (EventType.RUN_STATE, ScopeType.PROJECT),
    ]

    @mark.parametrize(
        ("event_type", "scope_type"),
        RUN_EVENT_SCOPES,
        indirect=True,
        ids=lambda v: v.value,
    )
    def test_update_scope_to_artifact_collection_fails_for_incompatible_event(
        self,
        module_api: wandb.Api,
        make_automation: Callable[[InputEvent, InputAction], Automation],
        event: InputEvent,
        action: InputAction,
        artifact_collection: ArtifactCollection,
    ):
        """Updating automation scope to an artifact collection fails if the event type doesn't support it."""
        old_automation = make_automation(event, action)

        with raises(CommError):
            old_automation.scope = artifact_collection
            module_api.update_automation(old_automation)

    MUTATION_EVENT_CLASSES = {
        EventType.ADD_ARTIFACT_ALIAS: OnAddArtifactAlias,
        EventType.LINK_ARTIFACT: OnLinkArtifact,
        EventType.CREATE_ARTIFACT: OnCreateArtifact,
    }

    @mark.parametrize(
        "event_type",
        sorted(MUTATION_EVENT_CLASSES.keys()),
        ids=lambda x: f"event={x.value}",
    )
    def test_update_event_preserves_filter(
        self,
        module_api: wandb.Api,
        old_automation: Automation,
        event_type: EventType,
        artifact_collection: ArtifactCollection,
    ):
        """Updating an automation with a new event must preserve its filter."""
        event_cls = self.MUTATION_EVENT_CLASSES[event_type]
        new_event = event_cls(
            scope=artifact_collection,
            filter=ArtifactEvent.alias == "prod",
        )
        expected_filter = new_event.filter

        updated = module_api.update_automation(old_automation, event=new_event)
        refetched = module_api.automation(name=old_automation.name)

        assert updated.event.event_type == event_type
        assert updated.event.filter.filter == expected_filter
        assert refetched.event.event_type == event_type
        assert refetched.event.filter.filter == expected_filter

    def test_update_non_event_fields_preserves_filter(
        self,
        module_api: wandb.Api,
        old_automation: Automation,
        make_name: Callable[[str], str],
    ):
        """Updating only the name must not alter the event filter."""
        original_filter = old_automation.event.filter
        new_name = make_name("renamed-automation")

        updated = module_api.update_automation(old_automation, name=new_name)

        assert updated.name == new_name
        assert updated.event.filter == original_filter

    RUN_EVENT_FACTORIES = {
        EventType.RUN_METRIC_THRESHOLD: lambda scope: OnRunMetric(
            scope=scope,
            filter=RunEvent.metric("my-metric").avg(5).gt(0),
        ),
        EventType.RUN_STATE: lambda scope: OnRunState(
            scope=scope,
            filter=RunEvent.state == "failed",
        ),
    }

    @mark.parametrize(
        "event_type",
        sorted(RUN_EVENT_FACTORIES),
        ids=lambda x: f"event={x.value}",
    )
    def test_update_run_event_preserves_filter(
        self,
        module_api: wandb.Api,
        make_automation: Callable[[InputEvent, InputAction], Automation],
        action: InputAction,
        event_type: EventType,
        project: Project,
    ):
        """Updating an automation with a new run event must preserve its filter."""
        if not module_api._supports_automation(event=event_type):
            skip(f"Server does not support event type {event_type.value!r}")

        # Run events only work with a project scope, and an update keeps the
        # automation's existing scope, so it must start out on a project.
        old_event = OnLinkArtifact(
            scope=project, filter=ArtifactEvent.alias.matches_regex("^my-artifact.*")
        )
        old_automation = make_automation(old_event, action)

        factory = self.RUN_EVENT_FACTORIES[event_type]
        new_event = factory(project)
        expected_filter = new_event.filter

        updated = module_api.update_automation(old_automation, event=new_event)
        refetched = module_api.automation(name=old_automation.name)

        assert updated.event.event_type == new_event.event_type
        assert updated.event.filter == expected_filter
        assert refetched.event.event_type == new_event.event_type
        assert refetched.event.filter == expected_filter

    @mark.parametrize(
        "updates",
        [
            {"name": "new-name"},
            {"description": "new-description"},
            {"enabled": False},
            {"description": "new-description", "enabled": False},
            {"name": "new-name", "enabled": False},
            {"name": "new-name", "description": "new-description", "enabled": False},
        ],
    )
    def test_update_via_kwargs(
        self,
        module_api: wandb.Api,
        old_automation: Automation,
        make_name: Callable[[str], str],
        updates: dict[str, Any],
    ):
        # Names are unique per scope, so give a renamed automation a fresh one.
        if name_prefix := updates.get("name"):
            updates = updates | {"name": make_name(name_prefix)}

        new_automation = module_api.update_automation(old_automation, **updates)
        for name, value in updates.items():
            assert getattr(new_automation, name) == value


class TestPaginatedAutomations:
    @fixture(scope="class")
    def num_projects(self) -> int:
        return 10

    @fixture(scope="class", params=[1, 2, 3])
    def page_size(self, request: FixtureRequest) -> int:
        return request.param

    @fixture(scope="class")
    def num_pages(self, num_projects: int, page_size: int) -> int:
        """The number of pages we'll expect to encounter via paginated requests."""
        # NOTE: For now, pagination is per project, NOT per automation
        return math.ceil(num_projects / page_size)

    @fixture(scope="class")
    def setup_paginated_automations(
        self,
        module_user: str,
        make_module_api: Callable[[], wandb.Api],
        webhook: WebhookIntegration,
        num_projects: int,
        make_name: Callable[[str], str],
    ):
        setup_api = make_module_api()

        # HACK: Is there a way to ensure a clean slate for each test?
        for id_ in setup_api.automations():
            setup_api.delete_automation(id_)

        # NOTE: For now, pagination is per project, NOT per automation, so
        # to test pagination, we'll create each automation in a separate project.
        #
        # UPDATE THIS in the future if we switch to per-automation pagination.
        project_names = [make_name(f"project-{i}") for i in range(num_projects)]
        automation_names = [make_name(f"automation-{i}") for i in range(num_projects)]

        created_automation_ids = deque()
        for project_name, automation_name in zip(
            project_names, automation_names, strict=True
        ):
            # Create the placeholder project for the automation
            setup_api.create_project(name=project_name, entity=module_user)
            project = setup_api.project(name=project_name, entity=module_user)

            # Create the actual automation
            event = OnLinkArtifact(scope=project)
            action = SendWebhook.from_integration(webhook)
            created = setup_api.create_automation(
                event >> action,
                name=automation_name,
                description="test description",
            )

            # Retain the automation ID for later cleanup.
            created_automation_ids.append(created.id)

        yield

        # This particular fixture is deliberately class-scoped, but clean up the automations for good measure
        cleanup_api = make_module_api()
        for id_ in created_automation_ids:
            cleanup_api.delete_automation(id_)

    @mark.usefixtures(setup_paginated_automations.__name__)
    def test_paginated_automations(
        self,
        mocker,
        module_user: str,
        module_api: wandb.Api,
        num_projects,
        page_size,
    ):
        # Spy on the service method that makes the GQL request.
        client_spy = mocker.spy(module_api._service_api, "execute_graphql")

        # Fetch the automations
        list(module_api.automations(entity=module_user, per_page=page_size))

        # Check that the number of GQL requests is at least what we expect from the pagination params
        # Note that a (cached) introspection query may add an extra request the first time this is
        # called.
        expected_page_count = math.ceil(num_projects / page_size)

        assert client_spy.call_count >= expected_page_count

    @mark.usefixtures(setup_paginated_automations.__name__)
    def test_paginated_automations_start(
        self,
        module_user: str,
        module_api: wandb.Api,
        page_size,
    ):
        all_automations = list(
            module_api.automations(entity=module_user, per_page=page_size)
        )
        all_ids = [a.id for a in all_automations]

        paginator = module_api.automations(entity=module_user, per_page=page_size)
        first_ids = [obj.id for obj in islice(paginator, page_size)]

        saved_cursor = paginator.cursor
        assert saved_cursor is not None

        resumed_paginator = module_api.automations(
            entity=module_user, per_page=page_size, start=saved_cursor
        )
        remaining_ids = [a.id for a in resumed_paginator]

        assert all_ids == [*first_ids, *remaining_ids]
