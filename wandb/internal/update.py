import wandb
import requests
from pkg_resources import parse_version


def check_available(current_version):
    timeout = 2  # Two seconds.
    pypi_url = 'https://pypi.org/pypi/wandb-ng/json'
    try:
        data = requests.get(pypi_url, timeout=timeout).json()
        latest_version = data['info']['version']
    except:
        # Any issues whatsoever, just skip the latest version check.
        return

    # Return if no update is available
    if parse_version(latest_version) <= parse_version(current_version):
        return

    # A new version is available!
    wandb.termlog(
        "wandb-ng version %s is available!  To upgrade, please run:\n $ pip install wandb-ng --upgrade" % latest_version)
