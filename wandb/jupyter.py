import logging
import re

import requests
from requests.compat import urljoin

logger = logging.getLogger(__name__)


def notebook_metadata():
    """Attempts to query jupyter for the path and name of the notebook file"""
    error_message = (
        "Failed to query for notebook name, you can set it manually with "
        "the WANDB_NOTEBOOK_NAME environment variable"
    )
    try:
        import ipykernel
        from notebook.notebookapp import list_running_servers

        kernel_id = re.search(
            "kernel-(.*).json", ipykernel.connect.get_connection_file()
        ).group(1)
        servers = list(
            list_running_servers()
        )  # TODO: sometimes there are invalid JSON files and this blows up
    except Exception:
        logger.error(error_message)
        return {}
    for s in servers:
        try:
            if s["password"]:
                raise ValueError("Can't query password protected kernel")
            res = requests.get(
                urljoin(s["url"], "api/sessions"), params={"token": s.get("token", "")}
            ).json()
        except (requests.RequestException, ValueError):
            logger.error(error_message)
            return {}
        for nn in res:
            # TODO: wandb/client#400 found a case where res returned an array of
            # strings...
            if isinstance(nn, dict) and nn.get("kernel") and "notebook" in nn:
                if nn["kernel"]["id"] == kernel_id:
                    return {
                        "root": s["notebook_dir"],
                        "path": nn["notebook"]["path"],
                        "name": nn["notebook"]["name"],
                    }
    return {}
