import os

import requests


def get_wandb_api_key() -> str:
    base_url = os.environ.get("WANDB_BASE_URL", "https://api.wandb.ai")
    api_key = os.environ.get("WANDB_API_KEY")
    if not api_key:
        auth = requests.utils.get_netrc_auth(base_url)
        if not auth:
            raise ValueError(
                f"must configure api key by env or in netrc for {base_url}"
            )
        api_key = auth[-1]
    return api_key


def get_wandb_api_key_file(file_name: str = None) -> str:
    file_name = file_name or ".wandb-api-key.secret"
    api_key = get_wandb_api_key()
    with open(file_name, "w") as f:
        f.write(api_key)
    return os.path.abspath(file_name)
