import logging

from wandb.sdk.integration_utils.llm import AutologLLMAPI

from .resolver import CohereRequestResponseResolver

logger = logging.getLogger(__name__)


autolog = AutologLLMAPI(
    name="Cohere",
    symbols=("Client.generate", "Client.chat", "Client.classify"),
    resolver=CohereRequestResponseResolver(),
    telemetry_feature="cohere_autolog",
)
