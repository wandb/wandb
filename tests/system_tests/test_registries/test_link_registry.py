from __future__ import annotations

from typing import Literal

import wandb
from pytest import FixtureRequest, fixture, mark
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
