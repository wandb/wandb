from __future__ import annotations

from typing import Literal

import wandb
from pytest import FixtureRequest, MonkeyPatch, fixture, mark, param, skip
from typing_extensions import assert_never
from wandb import Api, Artifact
from wandb.apis.public.registries.registry import Registry


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


@mark.usefixtures("skip_verify_login")
@mark.parametrize(
    ("org_role", "invite_to_source_team", "alias"),
    [
        param("member", False, "member-added-alias", id="org-member"),
        param("viewer", True, "viewer-registry-member-alias", id="org-viewer"),
    ],
)
def test_add_alias_to_linked_artifact_without_source_write(
    monkeypatch: MonkeyPatch,
    add_org_user_with_registry_access,
    org: str,
    team: str,
    registry: Registry,
    linked_version_name: str,
    org_role: Literal["member", "viewer"],
    invite_to_source_team: bool,
    alias: str,
    models_viewer_registry_write_supported: bool,
):
    """Users without source-project write access can still add aliases to linked artifacts."""
    if org_role == "viewer" and not models_viewer_registry_write_supported:
        skip(
            "Registry writes by a Models-Viewer seat need server v0.75.0 or newer. "
            "Gated on TOTAL_COUNT_IN_FILE_CONNECTION as a version proxy."
        )

    username, _user = add_org_user_with_registry_access(
        org=org,
        org_role=org_role,
        registry=registry,
        team=team,
        invite_to_source_team=invite_to_source_team,
    )

    monkeypatch.setenv("WANDB_API_KEY", username)
    monkeypatch.setenv("WANDB_ENTITY", username)

    viewer_api = Api(api_key=username)
    artifact = viewer_api.artifact(linked_version_name)

    if invite_to_source_team:
        assert artifact.source_entity and artifact.source_project
    else:
        assert not (artifact.source_entity and artifact.source_project)

    artifact.aliases.append(alias)
    artifact.save()

    reloaded = viewer_api.artifact(linked_version_name)
    assert alias in reloaded.aliases
