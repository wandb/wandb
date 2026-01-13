from __future__ import annotations

import os
from typing import Any

from wandb import env
from wandb.sdk import wandb_setup
from wandb.sdk.lib import wbauth


def sagemaker_auth(
    overrides: dict[str, Any] | None = None,
    path: str = ".",
    api_key: str | None = None,
) -> None:
    """Write a secrets.env file with the W&B ApiKey and any additional secrets passed.

    Args:
        overrides: Additional environment variables to write to secrets.env
        path: The path to write the secrets file.
    """
    overrides = overrides or dict()

    api_key = (
        overrides.get(env.API_KEY, None)
        or api_key
        or wandb_setup.singleton().settings.api_key
        or wbauth.read_netrc_auth(host=wandb_setup.singleton().settings.base_url)
    )

    if api_key is None:
        raise ValueError(
            "Can't find W&B API key, set the WANDB_API_KEY env variable"
            + " or run `wandb login`"
        )

    overrides[env.API_KEY] = api_key
    with open(os.path.join(path, "secrets.env"), "w") as file:
        for k, v in overrides.items():
            file.write(f"{k}={v}\n")
