import os
import subprocess
import time

import wandb
from wandb.server.service_server import ProcessManager  # type: ignore

from .lib import apikey


class Tunnel(object):
    def __init__(
        self, settings=None,
    ):
        self._settings = settings or wandb.setup().settings
        self._port = wandb.util.free_port()
        self._host = wandb.util.generate_id()
        self._server = ProcessManager(
            "server", {"port": self._port, "tempdir": ProcessManager.DIR}
        )
        self._tunnel = ProcessManager(
            "inlets",
            {
                "url": self._settings.base_url.replace("http", "ws"),
                "host": self._host,
                "port": self._port,
                "apikey": apikey.api_key(self._settings),
            },
        )

    def start(self, foreground=False, verbose=False):
        self._server.launch()
        self._tunnel.launch()
        if foreground:
            if verbose:
                subprocess.Popen(
                    [
                        "tail",
                        "-f",
                        os.path.join(ProcessManager.DIR, "logs", "server.log"),
                    ]
                )
            while True:
                if self._tunnel.status != "running":
                    break
                time.sleep(5)

    @property
    def url(self):
        return self._settings.base_url + "/service-redirect/proxies/" + self._host


_tunnel = None


def tunnel(foreground=False, verbose=False):
    global _tunnel
    if _tunnel:
        _tunnel.stop()
    else:
        _tunnel = Tunnel()
    wandb.termlog("Secure tunnel opened at: {}".format(_tunnel.url))
    wandb.termlog(
        "Control plane at: http://localhost:{}/api/status".format(_tunnel._port)
    )
    wandb.termlog("Logs at: {}".format(os.path.join(ProcessManager.DIR, "logs")))
    _tunnel.start(foreground=foreground, verbose=verbose)
    return _tunnel
