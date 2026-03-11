from __future__ import annotations

import contextlib
import uuid
import weakref

from wandb.proto.wandb_api_pb2 import ApiRequest, ApiResponse
from wandb.sdk import wandb_settings, wandb_setup
from wandb.sdk.lib.service.service_connection import ServiceConnection
from wandb.sdk.mailbox.mailbox_handle import MailboxHandle


def _cleanup(connection: ServiceConnection | None, api_id: str) -> None:
    """Clean up the api resources associated with the api id."""
    if connection is not None:
        with contextlib.suppress(Exception):
            connection.api_cleanup_request(api_id)


class ServiceApi:
    """A lazy initialized handle to the wandb-core service for handling API requests."""

    def __init__(
        self,
        settings: wandb_settings.Settings,
    ):
        self._settings = settings
        self._service_connection: ServiceConnection | None = None
        self._api_id = str(uuid.uuid4())

    def _get_service_connection(self) -> ServiceConnection:
        """Connects to the service and initializes resources for handling API requests."""
        if self._service_connection is None:
            self._service_connection = wandb_setup.singleton().ensure_service()
            response = self._service_connection.api_init_request(
                self._settings.to_proto(),
            )
            self._api_id = response.id

            weakref.finalize(
                self,
                _cleanup,
                self._service_connection,
                self._api_id,
            )

        return self._service_connection

    def send_api_request(
        self,
        request: ApiRequest,
        timeout: float | None = None,
    ) -> ApiResponse:
        """Send an API request to the backend service.

        Creates the backend service connection if it has not been created yet.
        """
        conn = self._get_service_connection()
        request.id = self._api_id
        return conn.api_request(request, timeout=timeout)

    async def send_api_request_async(
        self,
        request: ApiRequest,
    ) -> MailboxHandle[ApiResponse]:
        """Send an API request to the backend service asynchronously.

        Args:
            request: The Api request to send.
            timeout: The timeout for the request.
        """
        conn = self._get_service_connection()
        request.id = self._api_id
        return await conn.api_request_async(request)
