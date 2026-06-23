from __future__ import annotations

from typing import Literal

import wandb
from pytest import FixtureRequest, MonkeyPatch, fixture, mark
from typing_extensions import assert_never
from wandb import Api, Artifact
from wandb.apis._generated import IS_PROJECT_READ_ONLY_GQL, IsProjectReadOnly
from wandb.apis.public.registries.registry import Registry

from ..backend_fixtures import BackendFixtureFactory, OrgCmd, OrgMemberState, OrgState


@fixture(
    params=[
        ["alias1", "alias2"],
        ["alias1"],
        [],
        None,
    ]
)
def aliases(request: FixtureRequest) -> list[str] | None:
    """Test aliases to apply when linking an artifact."""
    return request.param


@fixture(
    params=[
        "{org_entity}/{registry_name}/{collection_name}",
        "{registry_name}/{collection_name}",
    ]
)
def target_path(
    request: FixtureRequest,
    org_entity: str,
    registry: Registry,
    target_collection_name: str,
) -> str:
    """Test target path to link to.

    Parameterized over equivalent valid representations of the same target.
    """
    # Link to a new collection for each test run
    path_template = request.param
    return path_template.format(
        org_entity=org_entity,
        registry_name=registry.full_name,
        collection_name=target_collection_name,
    )


@fixture(params=["by_run", "by_artifact"])
def linked_artifact(
    request: FixtureRequest,
    team: str,
    target_path: str,
    source_artifact: Artifact,
    aliases: list[str] | None,
) -> Artifact:
    """A fixture that links the artifact to a registry collection.

    This is parameterized to test that the behavior of `Artifact.link()` and `Run.link_artifact()`
    are equivalent.
    """
    # Link to the target collection
    mode: Literal["by_run", "by_artifact"] = request.param
    if mode == "by_run":
        with wandb.init(entity=team) as run:
            linked = run.link_artifact(source_artifact, target_path, aliases=aliases)

    elif mode == "by_artifact":
        linked = source_artifact.link(target_path, aliases=aliases)

    else:
        assert_never(mode)

    assert linked is not None  # precondition check
    return linked


@mark.usefixtures("set_team_as_default_entity")
def test_artifact_link_to_registry_collection(
    team: str,
    api: Api,
    org_entity: str,
    target_path: str,
    registry: Registry,
    source_artifact: Artifact,
    linked_artifact: Artifact,
    aliases: list[str] | None,
    target_collection_name: str,
    worker_id: str,
):
    linked = linked_artifact  # for brevity and convenience

    assert set(linked.aliases) == {"latest", *(aliases or [])}
    assert linked.collection.name == target_collection_name
    assert linked.collection.entity == org_entity
    assert linked.project == registry.full_name

    expected_linked_full_name = (
        f"{org_entity}/{registry.full_name}/{target_collection_name}:{linked.version}"
    )
    assert expected_linked_full_name == linked.qualified_name


# ---------------------------------------------------------------------------
# Linked-artifact saves when the caller lacks source-project write access
# ---------------------------------------------------------------------------


def _add_org_user(
    backend_fixture_factory: BackendFixtureFactory,
    org: str,
    *,
    org_role: str,
) -> str:
    username = backend_fixture_factory.make_user()
    backend_fixture_factory.send_cmds(
        OrgCmd(
            "add_members",
            orgName=org,
            fixtureData=OrgState(
                members=[OrgMemberState(username=username, role=org_role)]
            ),
        ),
    )
    return username


def _grant_registry_member_role(
    api: Api,
    registry: Registry,
    username: str,
) -> None:
    user = api.user(username)
    registry.add_members(user).update_member(user, role="member")


@fixture
def org_member_user(
    backend_fixture_factory: BackendFixtureFactory,
    org: str,
    registry: Registry,
    api: Api,
) -> str:
    """An org member with registry write access but no source-team access."""
    username = _add_org_user(backend_fixture_factory, org, org_role="member")
    _grant_registry_member_role(api, registry, username)
    return username


@fixture
def org_viewer_registry_member_user(
    backend_fixture_factory: BackendFixtureFactory,
    org: str,
    team: str,
    registry: Registry,
    api: Api,
) -> str:
    """An org viewer with registry ``member`` role and read-only source-team access."""
    username = _add_org_user(backend_fixture_factory, org, org_role="viewer")
    _grant_registry_member_role(api, registry, username)
    assert api.team(team).invite(username)
    return username


@fixture
def linked_version_name(
    source_artifact: Artifact,
    registry: Registry,
    target_collection_name: str,
) -> str:
    """Link the source artifact into a registry collection (as the owning admin)."""
    target_path = f"{registry.full_name}/{target_collection_name}"
    linked = source_artifact.link(target_path)
    source_artifact.wait()
    assert linked is not None  # precondition: link succeeded
    return linked.qualified_name


def _source_project_read_only(api: Api, artifact: Artifact) -> bool | None:
    """Return the source project's ``readOnly`` flag, or ``None`` if invisible."""
    data = api._service_api.execute_graphql(
        IS_PROJECT_READ_ONLY_GQL,
        variables={
            "entity": artifact.source_entity,
            "project": artifact.source_project,
        },
    )
    result = IsProjectReadOnly.model_validate(data)
    if not (result and (project := result.project)):
        return None
    return project.read_only


def _assert_cannot_write_to_source_project(
    api: Api,
    artifact: Artifact,
    *,
    guard: Literal["empty_source", "read_only"],
) -> None:
    """Assert ``_can_write_to_source_project()`` is False for the expected reason."""
    if guard == "empty_source":
        assert not artifact.source_entity or not artifact.source_project
    else:
        assert artifact.source_entity
        assert artifact.source_project
        assert _source_project_read_only(api, artifact) is True

    assert artifact._can_write_to_source_project() is False


def _assert_can_add_alias_to_linked_artifact(
    monkeypatch: MonkeyPatch,
    username: str,
    linked_version_name: str,
    alias: str,
    *,
    guard: Literal["empty_source", "read_only"],
) -> None:
    monkeypatch.setenv("WANDB_API_KEY", username)
    monkeypatch.setenv("WANDB_ENTITY", username)

    api = Api(api_key=username)
    artifact = api.artifact(linked_version_name)
    _assert_cannot_write_to_source_project(api, artifact, guard=guard)

    artifact.aliases.append(alias)
    artifact.save()

    reloaded = Api(api_key=username).artifact(linked_version_name)
    assert alias in reloaded.aliases


@mark.usefixtures("skip_verify_login")
def test_add_alias_to_linked_artifact_as_org_member(
    monkeypatch: MonkeyPatch,
    org_member_user: str,
    linked_version_name: str,
):
    """An org member with registry write access can add an alias without source write."""
    _assert_can_add_alias_to_linked_artifact(
        monkeypatch,
        org_member_user,
        linked_version_name,
        "member-added-alias",
        guard="empty_source",
    )


@mark.usefixtures("skip_verify_login")
def test_add_alias_to_linked_artifact_as_org_viewer_with_registry_member(
    monkeypatch: MonkeyPatch,
    org_viewer_registry_member_user: str,
    linked_version_name: str,
):
    """An org viewer with registry ``member`` role can add an alias when source is read-only."""
    _assert_can_add_alias_to_linked_artifact(
        monkeypatch,
        org_viewer_registry_member_user,
        linked_version_name,
        "viewer-registry-member-alias",
        guard="read_only",
    )
