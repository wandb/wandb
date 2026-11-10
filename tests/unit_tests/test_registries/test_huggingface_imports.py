from __future__ import annotations

import itertools
import json
import re
from typing import TYPE_CHECKING, Any, NamedTuple

from pytest import fixture, raises
from wandb.apis.public.api import Api
from wandb.apis.public.registries import (
    HuggingFaceImport,
    HuggingFaceImportError,
    Registry,
)
from wandb.errors.errors import CommError
from wandb.sdk.artifacts._generated import RegistryHuggingFaceImportFragment
from wandb.sdk.artifacts.exceptions import WaitTimeoutError
from wandb.sdk.lib.service.service_connection import WandbApiFailedError

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


def import_fragment_dict(
    state: str = "RUNNING",
    phase: str | None = "DOWNLOADING",
    events: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    fragment: dict[str, Any] = {
        "__typename": "RegistryHuggingFaceImport",
        "id": "aW1wb3J0OjEyMw==",
        "state": state,
        "phase": phase,
        "errorCode": None,
        "errorMessage": None,
        "stats": None,
        "createdAt": "2026-01-01T00:00:00Z",
        "terminalAt": None,
        "hfRepoId": "org/model",
        "hfRequestedRevision": "main",
        "hfResolvedRevision": None,
        "entity": {"name": "my-team"},
        "project": {"name": "huggingface-imports"},
        "registryProject": {"name": "wandb-registry-my-registry"},
        "registryCollectionName": "my-collection",
        "artifact": None,
        "artifactRef": None,
        "registryRef": None,
        "events": {"edges": [{"node": e} for e in (events or [])]},
    }
    fragment.update(overrides)
    return fragment


def event(event_id: str, name: str = "progress", message: str | None = None) -> dict:
    return {
        "id": event_id,
        "time": "2026-01-01T00:00:00Z",
        "name": name,
        "message": message,
    }


class GQLStub(NamedTuple):
    """A GraphQL stub: `calls` records (query, variables); `payloads` is the
    response queue. An Exception payload is raised instead of parsed."""

    calls: list
    payloads: list


@fixture
def gql(service_api: MagicMock) -> GQLStub:
    stub = GQLStub(calls=[], payloads=[])

    def side_effect(query, variables=None, timeout=None, *, parse=json.loads, **kwargs):
        stub.calls.append((query, variables))
        payload = stub.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return parse(json.dumps(payload))

    service_api.execute_graphql.side_effect = side_effect
    return stub


@fixture
def service_api(mocker: MockerFixture) -> MagicMock:
    from wandb.apis.public.service_api import ServiceApi

    return mocker.Mock(spec=ServiceApi)


@fixture
def api(service_api: MagicMock) -> Api:
    api = Api.__new__(Api)
    api._service_api = service_api
    api.settings = {"organization": "acme"}
    api._default_entity = "my-team"
    return api


@fixture
def registry(service_api: MagicMock) -> Registry:
    return Registry(
        service_api, organization="acme", entity="my-team", name="my-registry"
    )


class TestCheckHuggingFaceSource:
    def test_sends_variables_and_parses(self, api, service_api, gql):
        gql.payloads.append(
            {
                "organization": {
                    "registryHuggingFaceSource": {
                        "status": "OK",
                        "message": "ready",
                        "resolvedRevision": "abc123",
                        "sizeBytes": 42,
                        "files": [
                            {"path": "model.safetensors", "sizeBytes": 40},
                            {"path": "config.json", "sizeBytes": 2},
                        ],
                    }
                }
            }
        )

        source = api.check_huggingface_source(
            "org/model",
            revision="main",
            organization="acme",
            entity="my-team",
            token_secret_name="hf-token",
        )

        _, variables = gql.calls[0]
        assert variables == {
            "organization": "acme",
            "hfRepoId": "org/model",
            "hfRevision": "main",
            "hfTokenSecretName": "hf-token",
            "entityName": "my-team",
        }
        assert source.ok
        assert source.status == "OK"
        assert source.resolved_revision == "abc123"
        assert source.size_bytes == 42
        assert [f.path for f in source.files] == ["model.safetensors", "config.json"]

    def test_null_organization_raises(self, api, service_api, gql):
        gql.payloads.append({"organization": None})

        with raises(CommError, match="acme"):
            api.check_huggingface_source("org/model", organization="acme")


class TestImportFromHuggingFace:
    def test_input_fields(self, registry, service_api, gql):
        gql.payloads.append(
            {
                "createRegistryHuggingFaceImport": {
                    "registryHuggingFaceImport": import_fragment_dict()
                }
            }
        )

        registry.import_from_huggingface(
            "org/model",
            entity="my-team",
            project="huggingface-imports",
            collection="my-collection",
            revision="main",
            aliases=["prod"],
            file_paths=[],
            token_secret_name="hf-token",
        )

        _, variables = gql.calls[0]
        assert variables["input"] == {
            "entityName": "my-team",
            "projectName": "huggingface-imports",
            "hfRepoType": "MODEL",
            "hfRepoId": "org/model",
            "hfRevision": "main",
            "registry": {
                "registryName": "my-registry",
                "collectionName": "my-collection",
            },
            "aliases": ["prod"],
            "filePaths": [],
            "hfTokenSecretName": "hf-token",
            "idempotencyKey": variables["input"]["idempotencyKey"],
        }
        # A generated key is a 32-character hex string; None optionals
        # (e.g. hfResolvedRevision) are left out of the input.
        assert re.fullmatch(r"[0-9a-f]{32}", variables["input"]["idempotencyKey"])
        assert "hfResolvedRevision" not in variables["input"]

    def test_supplied_idempotency_key(self, registry, service_api, gql):
        gql.payloads.append(
            {
                "createRegistryHuggingFaceImport": {
                    "registryHuggingFaceImport": import_fragment_dict()
                }
            }
        )

        registry.import_from_huggingface(
            "org/model",
            entity="my-team",
            project="huggingface-imports",
            collection="my-collection",
            idempotency_key="my-key",
        )

        _, variables = gql.calls[0]
        assert variables["input"]["idempotencyKey"] == "my-key"

    def test_mutation_failure_mentions_key(self, registry, service_api, gql):
        gql.payloads.append(WandbApiFailedError("server says no"))

        with raises(CommError, match="my-key"):
            registry.import_from_huggingface(
                "org/model",
                entity="my-team",
                project="huggingface-imports",
                collection="my-collection",
                idempotency_key="my-key",
            )


def make_import(service_api: MagicMock, **overrides: Any) -> HuggingFaceImport:
    fragment = RegistryHuggingFaceImportFragment.model_validate(
        import_fragment_dict(**overrides)
    )
    return HuggingFaceImport(service_api, fragment)


class TestWait:
    def test_running_to_succeeded(self, service_api, gql, mocker: MockerFixture):
        mocker.patch("time.sleep")
        mocker.patch("time.monotonic")
        termlog = mocker.patch("wandb.apis.public.registries.huggingface.termlog")
        imp = make_import(service_api, events=[event("e1", "started")])
        gql.payloads.extend(
            [
                # refresh() -> still RUNNING, with a new event
                {
                    "registryHuggingFaceImport": import_fragment_dict(
                        events=[event("e1", "started"), event("e2", "halfway")]
                    )
                },
                # refresh() -> SUCCEEDED
                {
                    "registryHuggingFaceImport": import_fragment_dict(
                        state="SUCCEEDED",
                        phase=None,
                        terminalAt="2026-01-01T00:01:00Z",
                        events=[event("e1", "started"), event("e2", "halfway")],
                    )
                },
            ]
        )

        assert imp.wait() is imp

        messages = [str(c.args[0]) for c in termlog.call_args_list]
        assert sum("DOWNLOADING" in m for m in messages) == 1
        assert sum("e2" not in m and "started" in m for m in messages) == 1
        assert sum("halfway" in m for m in messages) == 1

    def test_failed_raises(self, service_api, mocker: MockerFixture):
        mocker.patch("time.sleep")
        mocker.patch("time.monotonic")
        mocker.patch("wandb.apis.public.registries.huggingface.termlog")
        imp = make_import(
            service_api,
            state="FAILED",
            errorCode="HF_TOKEN_INVALID",
            errorMessage="bad token",
        )

        with raises(HuggingFaceImportError, match="bad token") as exc_info:
            imp.wait()

        assert exc_info.value.state == "FAILED"
        assert exc_info.value.error_code == "HF_TOKEN_INVALID"

    def test_timeout(self, service_api, gql, mocker: MockerFixture):
        mocker.patch("time.sleep")
        mocker.patch("time.monotonic", side_effect=itertools.count(0, 10))
        mocker.patch("wandb.apis.public.registries.huggingface.termlog")
        imp = make_import(service_api)
        gql.payloads.append({"registryHuggingFaceImport": import_fragment_dict()})

        with raises(WaitTimeoutError):
            imp.wait(timeout=15.0)

    def test_no_refresh_after_deadline(self, service_api, gql, mocker: MockerFixture):
        sleep = mocker.patch("time.sleep")
        mocker.patch("time.monotonic", side_effect=[0.0, 0.0, 1.0])
        mocker.patch("wandb.apis.public.registries.huggingface.termlog")
        imp = make_import(service_api)

        with raises(WaitTimeoutError):
            imp.wait(timeout=1.0, poll_interval=5.0)

        sleep.assert_called_once_with(1.0)
        assert gql.calls == []

    def test_keyboard_interrupt(self, service_api, mocker: MockerFixture):
        mocker.patch("time.sleep", side_effect=KeyboardInterrupt)
        mocker.patch("time.monotonic")
        termlog = mocker.patch("wandb.apis.public.registries.huggingface.termlog")
        imp = make_import(service_api)

        with raises(KeyboardInterrupt):
            imp.wait()

        messages = [str(c.args[0]) for c in termlog.call_args_list]
        assert any("huggingface_import" in m and "still running" in m for m in messages)


class TestHuggingFaceImports:
    def test_paginates(self, api, service_api, gql):
        gql.payloads.extend(
            [
                {
                    "organization": {
                        "registryHuggingFaceImports": {
                            "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                            "edges": [
                                {"node": import_fragment_dict(id="aW1wb3J0OjE=")}
                            ],
                        }
                    }
                },
                {
                    "organization": {
                        "registryHuggingFaceImports": {
                            "pageInfo": {"hasNextPage": False, "endCursor": "c2"},
                            "edges": [
                                {"node": import_fragment_dict(id="aW1wb3J0OjI=")}
                            ],
                        }
                    }
                },
            ]
        )

        imports = api.huggingface_imports(
            "acme", states=["RUNNING"], include_deleted=True, per_page=1
        )
        results = list(imports)

        assert [i.id for i in results] == ["aW1wb3J0OjE=", "aW1wb3J0OjI="]
        _, vars1 = gql.calls[0]
        _, vars2 = gql.calls[1]
        assert vars1["states"] == ["RUNNING"]
        assert vars1["includeDeleted"] is True
        assert vars1["perPage"] == 1
        assert vars2["cursor"] == "c1"


class TestArtifactAccessors:
    def test_registry_artifact_parses_ref(self, service_api, mocker: MockerFixture):
        from wandb.sdk.artifacts.artifact import Artifact

        from_name = mocker.patch.object(Artifact, "_from_name")
        imp = make_import(
            service_api,
            registryRef="acme/wandb-registry-my-registry/my-collection:v0",
        )

        imp.registry_artifact()

        path = from_name.call_args.kwargs["path"]
        assert (path.prefix, path.project, path.name) == (
            "acme",
            "wandb-registry-my-registry",
            "my-collection:v0",
        )

    def test_none_before_success(self, service_api):
        imp = make_import(service_api)

        assert imp.artifact() is None
        assert imp.registry_artifact() is None
