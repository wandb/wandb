from typing import (
    Union,
)
import wandb
import tempfile
from wandb import util

MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")

def get_max_cli_version() -> Union[str, None]:
    _, server_info = wandb.api.viewer_server_info()
    max_cli_version = server_info.get("cliVersionInfo", {}).get("max_cli_version", None)
    return str(max_cli_version) if max_cli_version is not None else None

def is_numpy_array(data: object) -> bool:
    np = util.get_module(
        "numpy", required="Logging raw point cloud data requires numpy"
    )
    return isinstance(data, np.ndarray)