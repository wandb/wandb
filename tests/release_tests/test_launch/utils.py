import os
from netrc import netrc

import wandb


def get_wandb_api_key():
    if os.getenv("WANDB_API_KEY"):
        return
    wandb.login()
    n = netrc()
    # n.authenticators() returns tuple in format (login, account, key)
    api_key = n.authenticators("api.wandb.ai")[2]
    os.environ["WANDB_API_KEY"] = api_key
    return api_key
