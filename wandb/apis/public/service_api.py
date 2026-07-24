from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2 as spb
from wandb.proto.wandb_api_pb2 import (
    ApiRequest,
    ApiResponse,
    FeaturesRequest,
    GraphQLRequest,
)
from wandb.sdk import wandb_settings, wandb_setup
from wandb.sdk.lib.service.service_connection import (
    ServiceConnection,
    WandbApiFailedError,
)
from wandb.sdk.mailbox.mailbox_handle import MailboxHandle

_logger = logging.getLogger(__name__)


_T = TypeVar("_T")


@dataclass(frozen=True)
class _ServiceApiSession:
    connection: ServiceConnection
    api_id: str


class ServiceApi:
    """A lazy initialized handle to the wandb-core service for handling API requests."""

    def __init__(
        self,
        settings: wandb_settings.Settings,
        timeout: float | None = None,
    ):
        self._settings = settings
        self._timeout = timeout
        self._api_session: _ServiceApiSession | None = None

    @property
    def app_url(self) -> str:
        return self._settings.app_url.rstrip("/") + "/"

    def _get_api_session(self) -> _ServiceApiSession:
        """Connect to the service and initialize resources for API requests."""
        if self._api_session is not None:
            return self._api_session

        service_connection = wandb_setup.singleton().ensure_service()
        response = service_connection.api_init_request(self._settings.to_proto())
        session = _ServiceApiSession(
            connection=service_connection,
            api_id=response.api_id,
        )
        self._api_session = session

        # Clean up service-side resources when this object is GC'ed.
        cleanup_request = spb.ServerRequest()
        cleanup_request.api_cleanup_request.api_id = response.api_id
        service_connection.finalize(self, cleanup_request)

        return session

    def send_api_request(
        self,
        request: ApiRequest,
        timeout: float | None = None,
    ) -> ApiResponse:
        """Send an API request to the backend service.

        Creates the backend service connection if it has not been created yet.
        """
        session = self._get_api_session()
        request.api_id = session.api_id
        return session.connection.api_request(request, timeout=timeout)

    def finalize(
        self,
        obj: object,
        cleanup: ApiRequest,
    ) -> Callable[[], None]:
        """Send a cleanup request when the object is garbage collected.

        The request must not reference the object, or else it will never be
        garbage collected. The request is not guaranteed to be sent before
        the connection is closed, so any resource it would clean up must also be
        cleaned up automatically by wandb-core when this API instance is
        cleaned up.

        Returns:
            A callback that can be used to send the cleanup request immediately.
        """
        session = self._get_api_session()

        cleanup.api_id = session.api_id
        request = spb.ServerRequest(api_request=cleanup)

        return session.connection.finalize(obj, request)

    def execute_graphql(
        self,
        query: str,
        variables: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        *,
        parse: Callable[[str], _T] = json.loads,
        omit_variables: Iterable[str] | None = None,
        omit_fragments: Iterable[str] | None = None,
        omit_fields: Iterable[str] | None = None,
        rename_fields: Mapping[str, str] | None = None,
    ) -> _T:
        """Execute a GraphQL operation through the wandb-core sidecar.

        The query is sent to wandb-core, which performs the network round-trip
        against the W&B backend and returns the parsed `data` field of the
        GraphQL response.

        Args:
            query: The GraphQL document to execute.
            variables: Variables for the GraphQL operation, JSON-serialized
                on the wire.
            timeout: Optional timeout in seconds for waiting on wandb-core.
                On timeout, the request is cancelled on a best-effort basis.
            parse: Callable used to deserialize the JSON response data.
                Its must accept a (JSON) string as input. Its output will be
                returned from this method. Defaults to `json.loads`.
            omit_variables: Variable names ($var) to strip from the query
                server-side before forwarding to the backend. Use this to
                drop variables that the deployed server version does not
                support, leaving the rest of the query intact.
            omit_fragments: Fragment names to strip (both their definitions
                and any spreads referring to them).
            omit_fields: Field names to strip from selection sets. Aliased
                occurrences are also removed.
            rename_fields: Field renames applied to selection sets
                (`{old_name: new_name}`). Aliases are preserved.

        Returns:
            The decoded `data` field of the GraphQL response.

        Raises:
            WandbApiFailedError: The request failed for any reason, including
                timeouts while waiting on wandb-core, transport errors,
                non-successful HTTP status codes, and GraphQL `errors`
                returned by the server.
        """
        req = ApiRequest(
            graphql_request=GraphQLRequest(
                query=query,
                variables_json=json.dumps(variables or {}),
                omit_variables=omit_variables,
                omit_fragments=omit_fragments,
                omit_fields=omit_fields,
                rename_fields=rename_fields,
            )
        )
        resp = self.send_api_request(
            req,
            timeout=self._timeout if timeout is None else timeout,
        )
        return parse(resp.graphql_response.data_json)

    async def send_api_request_async(
        self,
        request: ApiRequest,
    ) -> MailboxHandle[ApiResponse]:
        """Send an API request to the backend service asynchronously.

        Args:
            request: The Api request to send.
            timeout: The timeout for the request.
        """
        session = self._get_api_session()
        request.api_id = session.api_id
        return await session.connection.api_request_async(request)

    def feature_enabled(
        self,
        feature: pb.ServerFeature | str,
        *,
        timeout: float = 10,
    ) -> bool:
        """Returns whether a single server feature is enabled.

        On timeout or normal error, this logs and returns False.

        Args:
            feature: The enum constant or name of the boolean feature to
                check. Prefer to use the enum constants when possible, since
                they have better type-checking. For unknown or incorrect names,
                this returns False.
            timeout: The timeout to use. Defaults to 10 seconds.
        """
        if isinstance(feature, str):
            try:
                # NOTE: pb.ServerFeature is not an actual runtime type.
                #
                # All protobuf enums are represented as integers.
                # It is guaranteed that the return value of Value
                # is a valid enum (if it exists), hence the cast.
                feature = cast(pb.ServerFeature, pb.ServerFeature.Value(feature))
            except ValueError:
                # SERVER_FEATURE_UNSPECIFIED is always disabled.
                return False

        req = ApiRequest(features_request=FeaturesRequest(features=[feature]))

        try:
            resp = self.send_api_request(req, timeout=timeout)
        except WandbApiFailedError:
            # NOTE: The feature's integer value is logged here.
            _logger.exception("Failed to load feature %s", feature)
            return False

        return feature in resp.features_response.enabled
