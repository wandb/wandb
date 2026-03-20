"""Sandbox wrapper with wandb integration.

- Auth
- Entity and Project from active wandb run, e.g. wandb.init(entity="foo", project="bar")
"""

from __future__ import annotations

import logging
import os
from typing import Any

import grpc
from cwsandbox import Sandbox as CWSandboxSandbox
from cwsandbox._defaults import (
    DEFAULT_BASE_URL,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    SandboxDefaults,
)
from cwsandbox._network import create_channel, parse_grpc_target
from cwsandbox._proto import atc_pb2, atc_pb2_grpc
from cwsandbox._sandbox import SandboxStatus, _translate_rpc_error
from cwsandbox.exceptions import SandboxError

from ._auth import SandboxAuthContext, resolve_auth_context

logger = logging.getLogger(__name__)


class Sandbox(CWSandboxSandbox):
    """W&B-aware wrapper around `cwsandbox.Sandbox`."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._wandb_auth_context: SandboxAuthContext | None = None

    @classmethod
    def session(
        cls,
        defaults: SandboxDefaults | None = None,
    ):
        from ._session import Session

        return Session(defaults)

    async def _ensure_client(self) -> None:
        if self._channel is not None:
            return

        # Instance operations are the one place where we can cheaply bind a
        # stable auth context to this sandbox without patching `cwsandbox`
        # process-wide.
        context = self._wandb_auth_context or resolve_auth_context()
        self._wandb_auth_context = context

        target, is_secure = parse_grpc_target(self._base_url)
        channel = create_channel(target, is_secure)
        stub = atc_pb2_grpc.ATCServiceStub(channel)  # type: ignore[no-untyped-call]
        self._channel = channel
        self._stub = stub
        self._auth_metadata = context.metadata
        logger.debug("Initialized W&B sandbox gRPC channel for %s", self._base_url)

    @classmethod
    async def _list_async(
        cls,
        *,
        tags: list[str] | None = None,
        status: str | None = None,
        runway_ids: list[str] | None = None,
        tower_ids: list[str] | None = None,
        include_stopped: bool = False,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> list[Sandbox]:
        # Upstream resolves auth inside this method body via a module-level
        # helper, so we currently need a local override to avoid a global patch.
        effective_base_url = (
            base_url or os.environ.get("CWSANDBOX_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else DEFAULT_REQUEST_TIMEOUT_SECONDS
        )

        status_enum = SandboxStatus(status) if status is not None else None
        auth_context = resolve_auth_context()
        auth_metadata = auth_context.metadata

        target, is_secure = parse_grpc_target(effective_base_url)
        channel = create_channel(target, is_secure)
        stub = atc_pb2_grpc.ATCServiceStub(channel)  # type: ignore[no-untyped-call]

        try:
            request_kwargs: dict[str, Any] = {}
            if tags:
                request_kwargs["tags"] = tags
            if status_enum:
                request_kwargs["status"] = status_enum.to_proto()
            if runway_ids is not None:
                request_kwargs["runway_ids"] = runway_ids
            if tower_ids is not None:
                request_kwargs["tower_ids"] = tower_ids
            if include_stopped:
                request_kwargs["include_stopped"] = True

            request = atc_pb2.ListSandboxesRequest(**request_kwargs)
            try:
                response = await stub.List(
                    request, timeout=timeout, metadata=auth_metadata
                )
            except grpc.RpcError as exc:
                raise _translate_rpc_error(exc, operation="List sandboxes") from exc

            sandboxes = [
                cls._from_sandbox_info(
                    sb,
                    base_url=effective_base_url,
                    timeout_seconds=timeout,
                )
                for sb in response.sandboxes
            ]
            for sandbox in sandboxes:
                sandbox._wandb_auth_context = auth_context
            return sandboxes
        finally:
            await channel.close(grace=None)

    @classmethod
    async def _from_id_async(
        cls,
        sandbox_id: str,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Sandbox:
        # Same reason as `_list_async`: upstream has no class-level auth hook
        # for this path yet, so we override the RPC entry point locally.
        effective_base_url = (
            base_url or os.environ.get("CWSANDBOX_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else DEFAULT_REQUEST_TIMEOUT_SECONDS
        )

        auth_context = resolve_auth_context()
        auth_metadata = auth_context.metadata

        target, is_secure = parse_grpc_target(effective_base_url)
        channel = create_channel(target, is_secure)
        stub = atc_pb2_grpc.ATCServiceStub(channel)  # type: ignore[no-untyped-call]

        try:
            request = atc_pb2.GetSandboxRequest(sandbox_id=sandbox_id)
            try:
                response = await stub.Get(
                    request, timeout=timeout, metadata=auth_metadata
                )
            except grpc.RpcError as exc:
                raise _translate_rpc_error(
                    exc, sandbox_id=sandbox_id, operation="Get sandbox"
                ) from exc

            sandbox = cls._from_sandbox_info(
                response,
                base_url=effective_base_url,
                timeout_seconds=timeout,
            )
            sandbox._wandb_auth_context = auth_context
            return sandbox
        finally:
            await channel.close(grace=None)

    @classmethod
    async def _delete_async(
        cls,
        sandbox_id: str,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        missing_ok: bool = False,
    ) -> None:
        # Same reason as `_list_async`: without an upstream hook, class-level
        # auth-sensitive operations need a wrapper-side override.
        effective_base_url = (
            base_url or os.environ.get("CWSANDBOX_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else DEFAULT_REQUEST_TIMEOUT_SECONDS
        )

        auth_metadata = resolve_auth_context().metadata

        target, is_secure = parse_grpc_target(effective_base_url)
        channel = create_channel(target, is_secure)
        stub = atc_pb2_grpc.ATCServiceStub(channel)  # type: ignore[no-untyped-call]

        try:
            request = atc_pb2.DeleteSandboxRequest(sandbox_id=sandbox_id)
            try:
                response = await stub.Delete(
                    request, timeout=timeout, metadata=auth_metadata
                )
            except grpc.RpcError as exc:
                if exc.code() == grpc.StatusCode.NOT_FOUND and missing_ok:
                    return
                raise _translate_rpc_error(
                    exc, sandbox_id=sandbox_id, operation="Delete sandbox"
                ) from exc

            if not response.success:
                raise SandboxError(
                    f"Failed to delete sandbox: {response.error_message}"
                )
        finally:
            await channel.close(grace=None)
