from __future__ import annotations

import sys
from dataclasses import dataclass, field

import pytest
import wandb

if sys.version_info < (3, 11):
    pytest.skip("wandb.sandbox requires Python 3.11+", allow_module_level=True)

import cwsandbox._sandbox as cwsandbox_sandbox
import wandb.sandbox as wandb_sandbox

class _FakeChannel:
    async def close(self, grace=None) -> None:
        _ = grace


@dataclass
class _SandboxStubCalls:
    start: list[dict[str, object]] = field(default_factory=list)
    stop: list[dict[str, object]] = field(default_factory=list)


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


def test_sandbox_run_uses_active_wandb_run_auth_headers(
    user,
    tmp_path,
    monkeypatch,
) -> None:
    calls = _patch_sandbox_stub(monkeypatch)

    with wandb.init(
        project="sandbox-auth-system-test",
        dir=str(tmp_path),
    ) as run:
        expected_headers = {"x-api-key": user}
        if run.entity:
            expected_headers["x-entity-id"] = run.entity
        if run.project:
            expected_headers["x-project-name"] = run.project

        with wandb_sandbox.Sandbox.run("sleep", "infinity") as sandbox:
            assert sandbox.sandbox_id == "sb-system-test"

    assert len(expected_headers) == 3
    assert len(calls.start) == 1
    assert dict(calls.start[0]["metadata"]) == expected_headers
    assert len(calls.stop) == 1
    assert dict(calls.stop[0]["metadata"]) == expected_headers


def test_sandbox_run_without_run_uses_api_key_only(
    user,
    monkeypatch,
) -> None:
    calls = _patch_sandbox_stub(monkeypatch)

    monkeypatch.delenv("WANDB_ENTITY", raising=False)
    monkeypatch.delenv("WANDB_PROJECT", raising=False)
    wandb.teardown()

    assert wandb.run is None

    with wandb_sandbox.Sandbox.run("sleep", "infinity") as sandbox:
        assert sandbox.sandbox_id == "sb-system-test"

    wandb.teardown()

    assert len(calls.start) == 1
    assert dict(calls.start[0]["metadata"]) == {"x-api-key": user}
    assert len(calls.stop) == 1
    assert dict(calls.stop[0]["metadata"]) == {"x-api-key": user}


def test_sandbox_run_fails_in_offline_mode(
    tmp_path,
    monkeypatch,
) -> None:
    calls = _patch_sandbox_stub(monkeypatch)

    with wandb.init(
        project="sandbox-auth-system-test",
        mode="offline",
        dir=str(tmp_path),
    ):
        with pytest.raises(
            wandb.UsageError,
            match="wandb.sandbox is not available in offline mode.",
        ):
            wandb_sandbox.Sandbox.run("sleep", "infinity")

    assert calls.start == []
    assert calls.stop == []
