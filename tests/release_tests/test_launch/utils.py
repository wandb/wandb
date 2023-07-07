import os
import subprocess
from netrc import netrc
from typing import Optional

import wandb


def run_cmd(command: str) -> None:
    subprocess.Popen(command.split(" ")).wait()


def run_cmd_async(command: str) -> subprocess.Popen:
    # Returns process. Terminate with process.kill()
    return subprocess.Popen(command.split(" "))


def get_wandb_api_key(base_url: Optional[str]) -> str:
    if not base_url:
        base_url = "api.wandb.ai"
    if os.getenv("WANDB_API_KEY"):
        return
    wandb.login()
    n = netrc()
    # n.authenticators() returns tuple in format (login, account, key)
    api_key = n.authenticators(base_url)[2]
    os.environ["WANDB_API_KEY"] = api_key
    return api_key
