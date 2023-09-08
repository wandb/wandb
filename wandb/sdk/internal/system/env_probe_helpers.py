import logging

from sentry_sdk.integrations.aws_lambda import get_lambda_bootstrap  # type: ignore

logger = logging.getLogger(__name__)


def is_aws_lambda() -> bool:
    """Check if we are running in a lambda environment."""
    lambda_bootstrap = get_lambda_bootstrap()
    if not lambda_bootstrap or not hasattr(lambda_bootstrap, "handle_event_request"):
        return False
    return True
