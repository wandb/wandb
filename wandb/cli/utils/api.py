import wandb
from wandb import wandb_sdk
from wandb.apis import InternalApi

_api = None  # caching api instance allows patching from unit tests


def _get_cling_api(reset=None):
    """Get a reference to the internal api with cling settings."""
    global _api
    if reset:
        _api = None
        wandb_sdk.wandb_setup._setup(_reset=True)
    if _api is None:
        # TODO(jhr): make a settings object that is better for non runs.
        # only override the necessary setting
        wandb.setup(settings=dict(_cli_only_mode=True))
        _api = InternalApi()
    return _api
