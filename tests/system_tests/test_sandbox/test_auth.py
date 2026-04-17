from __future__ import annotations

from dataclasses import dataclass, field

import cwsandbox._sandbox as cwsandbox_sandbox
import pytest
import wandb
from wandb.sandbox import Sandbox


class _FakeChannel:
    async def close(self, grace=None) -> None:
        _ = grace


@dataclass
class _SandboxStubCalls:
    start: list[dict[str, object]] = field(default_factory=list)
    stop: list[dict[str, object]] = field(default_factory=list)


# TODO: We need to update the stub once upstream changes on rename are merged
# https://github.com/coreweave/cwsandbox-client/pull/98
def _patch_sandbox_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> _SandboxStubCalls:
    calls = _SandboxStubCalls()

    class _FakeSandboxStub:
        def __init__(self, channel) -> None:
            self._channel = channel

        async def Start(self, request, timeout=None, metadata=None):  # noqa: N802
            calls.start.append(
                {
                    "request": request,
                    "timeout": timeout,
                    "metadata": metadata,
                }
            )
            return cwsandbox_sandbox.atc_pb2.StartSandboxResponse(
                sandbox_id="sb-system-test",
                service_address="",
                exposed_ports=[],
                applied_ingress_mode="",
                applied_egress_mode="",
            )

        async def Stop(self, request, timeout=None, metadata=None):  # noqa: N802
            calls.stop.append(
                {
                    "request": request,
                    "timeout": timeout,
                    "metadata": metadata,
                }
            )
            return cwsandbox_sandbox.atc_pb2.StopSandboxResponse(
                success=True,
                error_message="",
            )

    monkeypatch.setattr(
        cwsandbox_sandbox,
        "create_channel",
        lambda target, is_secure: _FakeChannel(),
    )
    monkeypatch.setattr(
        cwsandbox_sandbox.atc_pb2_grpc,
        "ATCServiceStub",
        _FakeSandboxStub,
    )
    return calls


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
        "x-api-key": user,
        "x-entity-id": "entity-from-settings",
        "x-project-name": "project-from-settings",
    }
    assert len(calls.start) == 1
    assert dict(calls.start[0]["metadata"]) == expected_headers
    assert len(calls.stop) == 1
    assert dict(calls.stop[0]["metadata"]) == expected_headers


def test_sandbox_run_ignore_run_override(
    user,
    monkeypatch,
) -> None:
    calls = _patch_sandbox_stub(monkeypatch)

    with wandb.init(project="project-from-run"):
        with Sandbox.run("sleep", "infinity") as sandbox:
            assert sandbox.sandbox_id == "sb-system-test"

    expected_headers = {
        "x-api-key": user,
        "x-entity-id": user,
    }
    assert len(calls.start) == 1
    assert dict(calls.start[0]["metadata"]) == expected_headers
    assert len(calls.stop) == 1
    assert dict(calls.stop[0]["metadata"]) == expected_headers


def test_sandbox_run_without_entity_or_project(
    user,
    monkeypatch,
) -> None:
    calls = _patch_sandbox_stub(monkeypatch)

    monkeypatch.delenv("WANDB_ENTITY", raising=False)
    monkeypatch.delenv("WANDB_PROJECT", raising=False)

    with Sandbox.run("sleep", "infinity") as sandbox:
        assert sandbox.sandbox_id == "sb-system-test"

    assert len(calls.start) == 1
    assert dict(calls.start[0]["metadata"]) == {"x-api-key": user}
    assert len(calls.stop) == 1
    assert dict(calls.stop[0]["metadata"]) == {"x-api-key": user}
