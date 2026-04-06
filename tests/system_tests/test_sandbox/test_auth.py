from __future__ import annotations

import importlib
import sys
import types

import pytest
import wandb

if sys.version_info < (3, 11):
    pytest.skip("wandb.sandbox requires Python 3.11+", allow_module_level=True)

import cwsandbox._sandbox as cwsandbox_sandbox
from cwsandbox._auth import _reset_auth_mode_for_testing


class _FakeChannel:
    async def close(self, grace=None) -> None:
        _ = grace


# TODO: sandbox without a run


def test_sandbox_run_uses_active_wandb_run_auth_headers(
    user,
    tmp_path,
    monkeypatch,
) -> None:
    start_calls: list[dict[str, object]] = []
    stop_calls: list[dict[str, object]] = []

    class _FakeSandboxStub:
        def __init__(self, channel) -> None:
            self._channel = channel

        async def Start(self, request, timeout=None, metadata=None):
            start_calls.append(
                {
                    "request": request,
                    "timeout": timeout,
                    "metadata": metadata,
                }
            )
            return types.SimpleNamespace(
                sandbox_id="sb-system-test",
                service_address="",
                exposed_ports=[],
                applied_ingress_mode="",
                applied_egress_mode="",
            )

        async def Stop(self, request, timeout=None, metadata=None):
            stop_calls.append(
                {
                    "request": request,
                    "timeout": timeout,
                    "metadata": metadata,
                }
            )
            return types.SimpleNamespace(success=True, error_message="")

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
    wandb_sandbox = importlib.import_module("wandb.sandbox")
    sandbox_auth = importlib.import_module("wandb.sandbox._auth")
    sandbox_auth._set_wandb_auth_mode()

    try:
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
    finally:
        _reset_auth_mode_for_testing()

    assert len(expected_headers) == 3
    assert len(start_calls) == 1
    assert dict(start_calls[0]["metadata"]) == expected_headers
    assert len(stop_calls) == 1
    assert dict(stop_calls[0]["metadata"]) == expected_headers


def test_sandbox_run_fails_in_offline_mode(
    tmp_path,
    monkeypatch,
) -> None:
    start_calls: list[dict[str, object]] = []

    class _FakeSandboxStub:
        def __init__(self, channel) -> None:
            self._channel = channel

        async def Start(self, request, timeout=None, metadata=None):
            start_calls.append(
                {
                    "request": request,
                    "timeout": timeout,
                    "metadata": metadata,
                }
            )
            return types.SimpleNamespace(
                sandbox_id="sb-system-test",
                service_address="",
                exposed_ports=[],
                applied_ingress_mode="",
                applied_egress_mode="",
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
    wandb_sandbox = importlib.import_module("wandb.sandbox")
    sandbox_auth = importlib.import_module("wandb.sandbox._auth")
    sandbox_auth._set_wandb_auth_mode()

    try:
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
    finally:
        _reset_auth_mode_for_testing()

    assert start_calls == []
