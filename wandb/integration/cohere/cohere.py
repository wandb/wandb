import logging

from wandb.sdk.integration_utils.auto_logging import AutologAPI

from .resolver import CohereRequestResponseResolver

logger = logging.getLogger(__name__)


autolog = AutologAPI(
    name="Cohere",
    symbols=(
        "Client.generate",
        "Client.chat",
        "Client.classify",
        "Client.summarize",
        "Client.rerank",
    ),
    resolver=CohereRequestResponseResolver(),
    telemetry_feature="cohere_autolog",
)
