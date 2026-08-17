from __future__ import annotations

from dataclasses import dataclass, field

import cwsandbox
import cwsandbox._sandbox as cwsandbox_sandbox
import pytest
import wandb
from wandb.sandbox import Sandbox


class _FakeChannel:
    async def close(self, grace=None) -> None:
        _ = grace


@dataclass
class _SandboxStubCalls:
    create: list[dict[str, object]] = field(default_factory=list)
    delete: list[dict[str, object]] = field(default_factory=list)


def _patch_sandbox_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> _SandboxStubCalls:
    calls = _SandboxStubCalls()

    class _FakeSandboxStub:
        def __init__(self, channel) -> None:
            self._channel = channel

        async def CreateSandbox(  # noqa: N802
            self, request, timeout=None, metadata=None
        ):
            calls.create.append(
                {
                    "request": request,
                    "timeout": timeout,
                    "metadata": metadata,
                }
            )
            return cwsandbox_sandbox.sandbox_pb2.Sandbox(
                sandbox_id="sb-system-test",
                status=cwsandbox_sandbox.sandbox_pb2.SandboxStatus(
                    state=cwsandbox_sandbox.sandbox_pb2.STATE_CREATING
                ),
            )

        async def GetSandbox(  # noqa: N802
            self, request, timeout=None, metadata=None
        ):
            _ = request, timeout, metadata
            return cwsandbox_sandbox.sandbox_pb2.Sandbox(
                sandbox_id="sb-system-test",
                status=cwsandbox_sandbox.sandbox_pb2.SandboxStatus(
                    state=cwsandbox_sandbox.sandbox_pb2.STATE_COMPLETED
                ),
            )

        async def DeleteSandbox(  # noqa: N802
            self, request, timeout=None, metadata=None
        ):
            calls.delete.append(
                {
                    "request": request,
                    "timeout": timeout,
                    "metadata": metadata,
                }
            )
            return cwsandbox_sandbox.sandbox_pb2.DeleteSandboxResponse()

    monkeypatch.setattr(
        cwsandbox_sandbox,
        "create_channel",
        lambda target, is_secure: _FakeChannel(),
    )
    monkeypatch.setattr(
        cwsandbox_sandbox.sandbox_pb2_grpc,
        "SandboxServiceStub",
        _FakeSandboxStub,
    )
    return calls


def _client_version_headers() -> dict[str, str]:
    """The client-version headers every request carries, with live versions.

    Derived from the installed package versions (the same source the client
    reads) so the assertions stay exact without breaking on version bumps.
    """
    return {
        "x-wandb-sdk-version": wandb.__version__,
        "x-cwsandbox-client-version": cwsandbox.__version__,
    }


def test_sandbox_run_uses_settings_entity_project(
    user,
    monkeypatch,
) -> None:
    calls = _patch_sandbox_stub(monkeypatch)

    monkeypatch.setenv("WANDB_ENTITY", "entity-from-settings")
    monkeypatch.setenv("WANDB_PROJECT", "project-from-settings")

    with Sandbox.run("sleep", "infinity") as sandbox:
        assert sandbox.sandbox_id == "sb-system-test"

    expected_headers = {
        "x-wandb-api-key": user,
        "x-entity-id": "entity-from-settings",
        "x-project-name": "project-from-settings",
        **_client_version_headers(),
    }
    assert len(calls.create) == 1
    assert dict(calls.create[0]["metadata"]) == expected_headers
    assert len(calls.delete) == 1
    assert dict(calls.delete[0]["metadata"]) == expected_headers


def test_sandbox_run_ignore_run_override(
    user,
    monkeypatch,
) -> None:
    calls = _patch_sandbox_stub(monkeypatch)

    with wandb.init(project="project-from-run"):
        with Sandbox.run("sleep", "infinity") as sandbox:
            assert sandbox.sandbox_id == "sb-system-test"

    expected_headers = {
        "x-wandb-api-key": user,
        "x-entity-id": user,
        **_client_version_headers(),
    }
    assert len(calls.create) == 1
    assert dict(calls.create[0]["metadata"]) == expected_headers
    assert len(calls.delete) == 1
    assert dict(calls.delete[0]["metadata"]) == expected_headers


def test_sandbox_run_without_entity_or_project(
    user,
    monkeypatch,
) -> None:
    calls = _patch_sandbox_stub(monkeypatch)

    monkeypatch.delenv("WANDB_ENTITY", raising=False)
    monkeypatch.delenv("WANDB_PROJECT", raising=False)

    with Sandbox.run("sleep", "infinity") as sandbox:
        assert sandbox.sandbox_id == "sb-system-test"

    expected_headers = {"x-wandb-api-key": user, **_client_version_headers()}
    assert len(calls.create) == 1
    assert dict(calls.create[0]["metadata"]) == expected_headers
    assert len(calls.delete) == 1
    assert dict(calls.delete[0]["metadata"]) == expected_headers
