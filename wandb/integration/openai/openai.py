import logging

from wandb.sdk.integration_utils.auto_logging import AutologAPI
from wandb.util import check_openai_version_is_major_version

from .resolver import OpenAIRequestResponseResolver

logger = logging.getLogger(__name__)

if check_openai_version_is_major_version():
    autolog = AutologAPI(
        name="OpenAI",
        symbols=(),
        resolver=OpenAIRequestResponseResolver(is_major_version=True),
        telemetry_feature="openai_autolog",
    )
else:
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
