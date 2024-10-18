import os

import wandb
from wandb import env


def sagemaker_auth(overrides=None, path=".", api_key=None):
    """Write a secrets.env file with the W&B ApiKey and any additional secrets passed.

    Args:
        overrides (dict, optional): Additional environment variables to write
                                    to secrets.env
        path (str, optional): The path to write the secrets file.
    """
    settings = wandb.setup().settings
    current_api_key = wandb.wandb_lib.apikey.api_key(settings=settings)

    overrides = overrides or dict()
    api_key = overrides.get(env.API_KEY, api_key or current_api_key)
    if api_key is None:
        raise ValueError(
            "Can't find W&B ApiKey, set the WANDB_API_KEY env variable "
            "or run `wandb login`"
        )
    overrides[env.API_KEY] = api_key
    with open(os.path.join(path, "secrets.env"), "w") as file:
        for k, v in overrides.items():
            file.write(f"{k}={v}\n")
