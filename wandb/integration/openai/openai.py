import logging

from wandb.sdk.integration_utils.auto_logging import AutologAPI

from .resolver import OpenAIRequestResponseResolver

logger = logging.getLogger(__name__)


autolog = AutologAPI(
    name="OpenAI",
    symbols=(
        "Edit.create",
        "Completion.create",
        "ChatCompletion.create",
        "Edit.acreate",
        "Completion.acreate",
        "ChatCompletion.acreate",
    ),
    resolver=OpenAIRequestResponseResolver(),
    telemetry_feature="openai_autolog",
)
