from typing import TYPE_CHECKING

from wandb.sdk.artifacts.storage_handlers.multi_handler import MultiHandler

if TYPE_CHECKING:
    from requests import Session


def get_multi_handler(session: "Session") -> MultiHandler:
    """Get the multi handler that contains all the other handlers."""
    from wandb.sdk.artifacts.storage_handlers.azure_handler import AzureHandler
    from wandb.sdk.artifacts.storage_handlers.gcs_handler import GCSHandler
    from wandb.sdk.artifacts.storage_handlers.http_handler import HTTPHandler
    from wandb.sdk.artifacts.storage_handlers.local_file_handler import LocalFileHandler
    from wandb.sdk.artifacts.storage_handlers.s3_handler import S3Handler
    from wandb.sdk.artifacts.storage_handlers.tracking_handler import TrackingHandler
    from wandb.sdk.artifacts.storage_handlers.wb_artifact_handler import (
        WBArtifactHandler,
    )
    from wandb.sdk.artifacts.storage_handlers.wb_local_artifact_handler import (
        WBLocalArtifactHandler,
    )

    return MultiHandler(
        handlers=[
            AzureHandler(),
            GCSHandler(),
            HTTPHandler(session, scheme="https"),
            HTTPHandler(session),
            LocalFileHandler(),
            S3Handler(),
            WBArtifactHandler(),
            WBLocalArtifactHandler(),
        ],
        default_handler=TrackingHandler(),
    )
