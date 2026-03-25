from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("cwsandbox")

from wandb.sandbox import Sandbox, Session
from wandb.sandbox._auth import SandboxAuthContext


@pytest.mark.asyncio
async def test_sandbox_ensure_client_binds_wandb_auth_metadata() -> None:
    sandbox = Sandbox(command="sleep", args=["infinity"])
    context = SandboxAuthContext(
        metadata=(
            ("x-api-key", "wandb-key"),
            ("x-entity-id", "entity"),
            ("x-project-name", "project"),
        ),
        strategy="wandb_api_key",
        entity="entity",
        project="project",
    )

    with (
        patch("wandb.sandbox._sandbox.resolve_auth_context", return_value=context),
        patch("cwsandbox._sandbox.create_channel"),
        patch("cwsandbox._sandbox.atc_pb2_grpc.ATCServiceStub"),
    ):
        await sandbox._ensure_client()

    assert sandbox._auth_metadata == context.metadata


@pytest.mark.asyncio
async def test_sandbox_list_returns_wrapper_instances_with_bound_metadata() -> None:
    from cwsandbox._proto import atc_pb2
    from google.protobuf import timestamp_pb2

    context = SandboxAuthContext(
        metadata=(
            ("x-api-key", "wandb-key"),
            ("x-entity-id", "entity"),
            ("x-project-name", "project"),
        ),
        strategy="wandb_api_key",
        entity="entity",
        project="project",
    )
    sandbox_info = atc_pb2.SandboxInfo(
        sandbox_id="test-123",
        sandbox_status=atc_pb2.SANDBOX_STATUS_RUNNING,
        started_at_time=timestamp_pb2.Timestamp(seconds=1234567890),
        tower_id="tower-1",
        tower_group_id="group-1",
        runway_id="runway-1",
    )

    mock_channel = MagicMock()
    mock_channel.close = AsyncMock()
    mock_stub = MagicMock()
    mock_stub.List = AsyncMock(
        return_value=atc_pb2.ListSandboxesResponse(sandboxes=[sandbox_info])
    )

    with (
        patch("wandb.sandbox._sandbox.resolve_auth_context", return_value=context),
        patch("cwsandbox._sandbox.parse_grpc_target", return_value=("test:443", True)),
        patch("cwsandbox._sandbox.create_channel", return_value=mock_channel),
        patch("cwsandbox._sandbox.atc_pb2_grpc.ATCServiceStub", return_value=mock_stub),
    ):
        sandboxes = await Sandbox.list(tags=["test-tag"])

    assert len(sandboxes) == 1
    assert isinstance(sandboxes[0], Sandbox)
    assert sandboxes[0]._auth_metadata == context.metadata


@pytest.mark.asyncio
async def test_sandbox_delete_uses_wandb_auth_metadata() -> None:
    from cwsandbox._proto import atc_pb2

    context = SandboxAuthContext(
        metadata=(
            ("x-api-key", "wandb-key"),
            ("x-entity-id", "entity"),
            ("x-project-name", "project"),
        ),
        strategy="wandb_api_key",
        entity="entity",
        project="project",
    )

    mock_channel = MagicMock()
    mock_channel.close = AsyncMock()
    mock_stub = MagicMock()
    mock_stub.Delete = AsyncMock(
        return_value=atc_pb2.DeleteSandboxResponse(success=True, error_message="")
    )

    with (
        patch("wandb.sandbox._sandbox.resolve_auth_context", return_value=context),
        patch("cwsandbox._sandbox.parse_grpc_target", return_value=("test:443", True)),
        patch("cwsandbox._sandbox.create_channel", return_value=mock_channel),
        patch("cwsandbox._sandbox.atc_pb2_grpc.ATCServiceStub", return_value=mock_stub),
    ):
        await Sandbox.delete("test-123")

    call_kwargs = mock_stub.Delete.call_args[1]
    assert call_kwargs["metadata"] == context.metadata


def test_sandbox_session_returns_wrapper_session() -> None:
    session = Sandbox.session()

    assert isinstance(session, Session)


def test_session_sandbox_returns_wrapper_sandbox() -> None:
    session = Session()

    sandbox = session.sandbox(command="sleep", args=["infinity"])

    assert isinstance(sandbox, Sandbox)
    assert sandbox._session is session


@pytest.mark.asyncio
async def test_session_list_returns_wrapper_instances() -> None:
    from cwsandbox._proto import atc_pb2
    from google.protobuf import timestamp_pb2

    context = SandboxAuthContext(
        metadata=(
            ("x-api-key", "wandb-key"),
            ("x-entity-id", "entity"),
            ("x-project-name", "project"),
        ),
        strategy="wandb_api_key",
        entity="entity",
        project="project",
    )
    sandbox_info = atc_pb2.SandboxInfo(
        sandbox_id="test-123",
        sandbox_status=atc_pb2.SANDBOX_STATUS_RUNNING,
        started_at_time=timestamp_pb2.Timestamp(seconds=1234567890),
        tower_id="tower-1",
        tower_group_id="group-1",
        runway_id="runway-1",
    )

    session = Session()

    mock_channel = MagicMock()
    mock_channel.close = AsyncMock()
    mock_stub = MagicMock()
    mock_stub.List = AsyncMock(
        return_value=atc_pb2.ListSandboxesResponse(sandboxes=[sandbox_info])
    )

    with (
        patch("wandb.sandbox._sandbox.resolve_auth_context", return_value=context),
        patch("cwsandbox._sandbox.parse_grpc_target", return_value=("test:443", True)),
        patch("cwsandbox._sandbox.create_channel", return_value=mock_channel),
        patch("cwsandbox._sandbox.atc_pb2_grpc.ATCServiceStub", return_value=mock_stub),
    ):
        sandboxes = await session.list()

    assert len(sandboxes) == 1
    assert isinstance(sandboxes[0], Sandbox)
    assert sandboxes[0]._auth_metadata == context.metadata


@pytest.mark.asyncio
async def test_session_from_id_returns_wrapper_instance() -> None:
    from cwsandbox._proto import atc_pb2
    from google.protobuf import timestamp_pb2

    context = SandboxAuthContext(
        metadata=(
            ("x-api-key", "wandb-key"),
            ("x-entity-id", "entity"),
            ("x-project-name", "project"),
        ),
        strategy="wandb_api_key",
        entity="entity",
        project="project",
    )
    response = atc_pb2.GetSandboxResponse(
        sandbox_id="test-123",
        sandbox_status=atc_pb2.SANDBOX_STATUS_RUNNING,
        started_at_time=timestamp_pb2.Timestamp(seconds=1234567890),
        tower_id="tower-1",
        tower_group_id="group-1",
        runway_id="runway-1",
    )

    session = Session()

    mock_channel = MagicMock()
    mock_channel.close = AsyncMock()
    mock_stub = MagicMock()
    mock_stub.Get = AsyncMock(return_value=response)

    with (
        patch("wandb.sandbox._sandbox.resolve_auth_context", return_value=context),
        patch("cwsandbox._sandbox.parse_grpc_target", return_value=("test:443", True)),
        patch("cwsandbox._sandbox.create_channel", return_value=mock_channel),
        patch("cwsandbox._sandbox.atc_pb2_grpc.ATCServiceStub", return_value=mock_stub),
    ):
        sandbox = await session.from_id("test-123")

    assert isinstance(sandbox, Sandbox)
    assert sandbox._auth_metadata == context.metadata


@pytest.mark.asyncio
async def test_session_remote_function_uses_managed_wrapper_sandbox() -> None:
    session = Session()

    @session.function()
    def add(x: int, y: int) -> int:
        return x + y

    mock_sandbox = MagicMock()
    mock_sandbox.__aenter__ = AsyncMock(return_value=mock_sandbox)
    mock_sandbox.__aexit__ = AsyncMock(return_value=None)
    mock_sandbox._start_async = AsyncMock(return_value=None)
    mock_sandbox.sandbox_id = "test-sandbox-id"
    mock_sandbox.write_file = AsyncMock(return_value=None)
    mock_sandbox.exec = AsyncMock(return_value=MagicMock(returncode=0, stderr=""))
    mock_sandbox.read_file = AsyncMock(return_value=json.dumps(5).encode())

    with patch.object(
        session, "_create_managed_sandbox", return_value=mock_sandbox
    ) as mock_create:
        result = await add.remote(2, 3)

    assert result == 5
    mock_create.assert_called_once_with(container_image=None)
