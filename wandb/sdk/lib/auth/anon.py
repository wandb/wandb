"""The 'anonymous' mode allows using W&B without an account."""

from wandb.apis import InternalApi
from wandb.sdk import wandb_setup


def make_anonymous_api_key(*, host: str) -> str:
    """Create a new API key for an anonymous user.

    Args:
        host: The URL to the W&B server.

    Returns:
        A new API key.

    Raises:
        Exception: If there was a network error, the backend returned
            an error response, or a programming error occurred.
    """
    settings_for_host = wandb_setup.singleton().settings.model_copy()
    settings_for_host.base_url = host  # raises if host format is wrong

    api = InternalApi(settings_for_host)

    # TODO: Move implementation here and provide better exception guarantees.
    return api.create_anonymous_api_key()
