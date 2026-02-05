from __future__ import annotations

from wandb.proto.wandb_api_pb2 import ApiRequest, ApiResponse
from wandb.sdk import wandb_settings, wandb_setup
from wandb.sdk.lib.service import service_connection
from wandb.sdk.lib.service.service_connection import ServiceConnection
from wandb.sdk.mailbox.mailbox_handle import MailboxHandle


class ServiceAPI:
    """Class that maintains necessary information to interact with wandb-core."""

    def __init__(
        self,
        settings: wandb_settings.Settings,
    ):
        self._settings = settings
        self._service_connection: ServiceConnection | None = None

    def _get_service_connection(self) -> ServiceConnection:
        """Connects to the service and initializes resources for handling API requests.

        Creates a new connection to the wandb-core service process,
        allowing each API instance to have its own connection with independent settings.
        """
        if self._service_connection is None:
            self._service_connection = service_connection.connect_to_service(
                asyncer=wandb_setup.singleton().asyncer,
                settings=self._settings,
            )

            # Initialize API resources with our settings
            self._service_connection.api_init_request(self._settings.to_proto())

        return self._service_connection

    def send_api_request(
        self,
        request: ApiRequest,
        timeout: float | None = None,
    ) -> ApiResponse:
        """Sends an API request to the backend service.

        Creates the backend service attribute if it has not been created yet.

        TODO: remove this helper function once all requests are routed through wandb-core.
        The backend service should be created and initialized
        during the instantiation of the Api object.
        """
        conn = self._get_service_connection()
        return conn.api_request(request, timeout=timeout)

    async def _send_api_request_async(
        self,
        request: ApiRequest,
        timeout: float | None = None,
    ) -> MailboxHandle[ApiResponse]:
        """Sends an API request to the backend service asynchronously.

        Args:
            request: The API request to send.
            timeout: The timeout for the request.
        """
        conn = self._get_service_connection()
        return await conn.api_request_async(request)
