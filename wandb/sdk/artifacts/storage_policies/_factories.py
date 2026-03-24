from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ..storage_handler import StorageHandler
from ..storage_handlers.azure_handler import AzureHandler
from ..storage_handlers.gcs_handler import GCSHandler
from ..storage_handlers.http_handler import HTTPHandler
from ..storage_handlers.local_file_handler import LocalFileHandler
from ..storage_handlers.s3_handler import S3Handler
from ..storage_handlers.wb_artifact_handler import WBArtifactHandler
from ..storage_handlers.wb_local_artifact_handler import WBLocalArtifactHandler

if TYPE_CHECKING:
    from requests import Response, Session


HTTP_POOL_CONNECTIONS: Final[int] = 64
HTTP_POOL_MAXSIZE: Final[int] = 64


def raise_for_status(response: Response, *_, **__) -> None:
    """A `requests.Session` hook to raise for status on all requests."""
    response.raise_for_status()


def make_http_session() -> Session:
    """Return a `requests.Session` configured for artifact storage handlers."""
    from requests import Session
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    from wandb.sdk import wandb_setup

    # Sleep length: 0, 2, 4, 8, 16, 32, 64, 120, 120, 120, 120, 120, 120, 120, 120, 120
    # seconds, i.e. a total of 20min 6s.
    HTTP_RETRY_STRATEGY: Final[Retry] = Retry(  # noqa: N806
        backoff_factor=1,
        total=16,
        # 401, 403 are not retried because expired presigned url
        # requires calling graphql to get a new url. Upper layer such as
        # _download_chunk_with_refresh in _multipart handles refresh.
        status_forcelist=(308, 408, 409, 429, 500, 502, 503, 504),
    )

    session = Session()
    # Use the global settings singleton which already includes env var updates.
    settings = wandb_setup.singleton().settings
    headers = settings.x_extra_http_headers or {}
    session.headers.update(headers)

    # Explicitly configure the retry strategy for http/https adapters.
    adapter = HTTPAdapter(
        max_retries=HTTP_RETRY_STRATEGY,
        pool_connections=HTTP_POOL_CONNECTIONS,
        pool_maxsize=HTTP_POOL_MAXSIZE,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # Always raise on HTTP status errors.
    session.hooks["response"].append(raise_for_status)
    return session


def make_storage_handlers(session: Session) -> list[StorageHandler]:
    """A factory that returns the default artifact storage handlers."""
    return [
        S3Handler(),  # s3
        GCSHandler(),  # gcs
        AzureHandler(),  # azure
        HTTPHandler(session, scheme="http"),  # http
        HTTPHandler(session, scheme="https"),  # https
        WBArtifactHandler(),  # artifact
        WBLocalArtifactHandler(),  # local_artifact
        LocalFileHandler(),  # file_handler
    ]
