"""Manage wandb processes.

Create a grpc manager channel.
"""

import atexit
import os
import sys
from typing import Optional, Tuple, TYPE_CHECKING

from wandb import env

if TYPE_CHECKING:
    from wandb.sdk.service import grpc_service


class _ManagerToken:
    _token_str: Optional[str]

    def __init__(self) -> None:
        self._token_str = None

    def probe(self) -> None:
        token = os.environ.get(env.MANAGER_TOKEN)
        if not token:
            return
        self._token_str = token

    def configure(self, port: int) -> None:
        version = "1"
        pid = os.getpid()
        token = "-".join([version, str(pid), str(port)])
        os.environ[env.MANAGER_TOKEN] = token
        self._token_str = token

    def parse(self) -> Tuple[str, int, int]:
        assert self._token_str
        parts = self._token_str.split("-")
        assert len(parts) == 3, f"token must have 3 parts: {parts}"
        # TODO: make more robust?
        version, pid_str, port_str = parts
        pid_int = int(pid_str)
        port_int = int(port_str)
        return version, pid_int, port_int

    @property
    def token(self) -> Optional[str]:
        return self._token_str

    @property
    def port(self) -> int:
        _, _, port = self.parse()
        return port


class _Manager:
    _token: _ManagerToken

    def __init__(self) -> None:
        # TODO: warn if user doesnt have grpc installed
        from wandb.sdk.service import grpc_service

        self._token = _ManagerToken()
        self._service = grpc_service._Service()
        self._setup()

    def _setup(self) -> None:
        self._token.probe()
        if not self._token.token:
            self._setup_service()

        port = self._token.port
        self._service.connect(port=port)

    def _setup_service(self) -> None:
        port = self._service.start()
        assert port
        self._token.configure(port=port)
        self._atexit_setup()

    def _atexit_setup(self) -> None:
        print(
            "%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%% atexit register", file=sys.stderr
        )
        atexit.register(lambda: self._atexit_teardown())

    def _atexit_teardown(self) -> None:
        print("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%% atexit cleanup", file=sys.stderr)

    def _teardown(self) -> None:
        pass

    def _get_service(self) -> "grpc_service._Service":
        return self._service

    def _inform_init(self) -> None:
        svc = self._service
        assert svc
        svc._svc_inform_init()

    def _inform_finish(self) -> None:
        svc = self._service
        assert svc
        svc._svc_inform_finish()
