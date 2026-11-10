from __future__ import annotations

import json
from typing import Any

from pytest import fixture, mark, raises
from wandb.apis.public.artifacts import (
    ArtifactCollection,
    ArtifactCollections,
    ArtifactFiles,
    Artifacts,
    ArtifactType,
    ArtifactTypes,
    ProjectArtifactCollections,
    _ArtifactCollectionAliases,
)

PROJECT_NOT_FOUND = (
    "project 'my-project' not found under entity 'my-entity', "
    "or you don't have access to it"
)
TYPE_NOT_FOUND = "artifact type 'model' not found in 'my-entity/my-project'"
COLLECTION_NOT_FOUND = (
    "artifact collection 'my-collection' of type 'model' "
    "not found in 'my-entity/my-project'"
)


@fixture
def service_api(mocker):
    return mocker.MagicMock()


def respond_with(service_api, data: dict[str, Any]) -> None:
    def execute_graphql(*_args, parse=json.loads, **_kwargs):
        return parse(json.dumps(data))

    service_api.execute_graphql.side_effect = execute_graphql


@mark.parametrize(
    ("data", "message"),
    [
        ({"project": None}, PROJECT_NOT_FOUND),
        ({"project": {"artifactType": None}}, TYPE_NOT_FOUND),
        (
            {"project": {"artifactType": {"artifactCollection": None}}},
            COLLECTION_NOT_FOUND,
        ),
    ],
)
def test_artifacts_not_found(service_api, data, message):
    respond_with(service_api, data)
    artifacts = Artifacts(
        service_api, "my-entity", "my-project", "my-collection", "model"
    )

    with raises(ValueError) as exc_info:
        list(artifacts)

    assert str(exc_info.value) == message


@mark.parametrize(
    ("data", "message"),
    [
        ({"project": None}, PROJECT_NOT_FOUND),
        ({"project": {"artifactType": None}}, TYPE_NOT_FOUND),
    ],
)
def test_artifact_collections_not_found(service_api, data, message):
    respond_with(service_api, data)
    collections = ArtifactCollections(service_api, "my-entity", "my-project", "model")

    with raises(ValueError) as exc_info:
        list(collections)

    assert str(exc_info.value) == message


def test_project_artifact_collections_project_not_found(service_api):
    respond_with(service_api, {"project": None})
    collections = ProjectArtifactCollections(service_api, "my-entity", "my-project")

    with raises(ValueError) as exc_info:
        list(collections)

    assert str(exc_info.value) == PROJECT_NOT_FOUND


def test_artifact_types_project_not_found(service_api):
    respond_with(service_api, {"project": None})
    types = ArtifactTypes(service_api, "my-entity", "my-project")

    with raises(ValueError) as exc_info:
        list(types)

    assert str(exc_info.value) == PROJECT_NOT_FOUND


def test_artifact_collection_aliases_collection_not_found(service_api):
    respond_with(service_api, {"artifactCollection": None})
    aliases = _ArtifactCollectionAliases(service_api, "Q29sbGVjdGlvbjox")

    with raises(ValueError) as exc_info:
        list(aliases)

    assert str(exc_info.value) == (
        "artifact collection with ID 'Q29sbGVjdGlvbjox' not found, "
        "or you don't have access to it"
    )


@mark.parametrize(
    ("data", "message"),
    [
        ({"project": None}, PROJECT_NOT_FOUND),
        (
            {"project": {"artifactCollection": None}},
            "artifact collection 'my-collection' not found in 'my-entity/my-project'",
        ),
        (
            {
                "project": {
                    "artifactCollection": {
                        "__typename": "ArtifactSequence",
                        "artifactMembership": None,
                    }
                }
            },
            "artifact 'my-collection:v3' not found in 'my-entity/my-project'",
        ),
    ],
)
def test_artifact_files_not_found(mocker, service_api, data, message):
    mocker.patch("wandb.apis.public.artifacts.server_supports", return_value=True)
    respond_with(service_api, data)
    artifact = mocker.Mock(
        entity="my-entity",
        project="my-project",
        version="v3",
    )
    artifact.name = "my-collection:v3"
    files = ArtifactFiles(service_api, artifact)

    with raises(ValueError) as exc_info:
        list(files)

    assert str(exc_info.value) == message


@mark.parametrize(
    ("data", "message"),
    [
        ({"project": None}, PROJECT_NOT_FOUND),
        ({"project": {"artifactType": None}}, TYPE_NOT_FOUND),
        (
            {"project": {"artifactType": {"artifactCollection": None}}},
            COLLECTION_NOT_FOUND,
        ),
    ],
)
def test_artifact_collection_load_not_found(service_api, data, message):
    respond_with(service_api, data)

    with raises(ValueError) as exc_info:
        ArtifactCollection(
            service_api, "my-entity", "my-project", "my-collection", "model"
        )

    assert str(exc_info.value) == message


@mark.parametrize(
    ("data", "message"),
    [
        ({"project": None}, PROJECT_NOT_FOUND),
        ({"project": {"artifactType": None}}, TYPE_NOT_FOUND),
    ],
)
def test_artifact_type_load_not_found(service_api, data, message):
    respond_with(service_api, data)

    with raises(ValueError) as exc_info:
        ArtifactType(service_api, "my-entity", "my-project", "model")

    assert str(exc_info.value) == message
