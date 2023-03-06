import logging
import sys
from typing import Any, Optional

from sentry_sdk.integrations.aws_lambda import get_lambda_bootstrap

logger = logging.getLogger(__name__)


def is_aws_lambda() -> bool:
    """Check if we are running in a lambda environment."""
    lambda_bootstrap = get_lambda_bootstrap()
    if not lambda_bootstrap or not hasattr(lambda_bootstrap, "handle_event_request"):
        return False
    return True


def get_lambda_context() -> Optional[Any]:
    """Get the lambda context if running in a lambda environment."""
    if get_lambda_bootstrap():
        return sys._getframe(1).f_locals.get("context")
    return None


def get_lambda_request() -> Optional[Any]:
    """Get the lambda request if running in a lambda environment."""
    if get_lambda_bootstrap():
        return sys._getframe(1).f_locals.get("event")
    return None


def get_lambda_response() -> Optional[Any]:
    """Get the lambda response if running in a lambda environment."""
    if get_lambda_bootstrap():
        return sys._getframe(1).f_locals.get("response")
    return None


def get_lambda_handler() -> Optional[Any]:
    """Get the lambda handler if running in a lambda environment."""
    if get_lambda_bootstrap():
        return sys._getframe(1).f_locals.get("handler")
    return None


def get_lambda_function_name() -> Optional[str]:
    """Get the lambda function name if running in a lambda environment."""
    context = get_lambda_context()
    if context:
        return context.function_name
    return None


def get_lambda_function_version() -> Optional[str]:
    """Get the lambda function version if running in a lambda environment."""
    context = get_lambda_context()
    if context:
        return context.function_version
    return None
