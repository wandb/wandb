"""Manage wandb processes.

Create a grpc manager channel.
"""

import atexit
import os
import sys
from typing import Optional

from wandb import env


class _ManagerToken:
    _token_str: Optional[str]

    def __init__(self) -> None:
        self._token_str = None

    def probe(self) -> None:
        token = os.environ.get(env.MANAGER_TOKEN)
        if not token:
            return
        self._token_str = token

    def configure(self) -> None:
        version = "1"
        pid = os.getpid()
        token = "-".join([version, str(pid)])
        os.environ[env.MANAGER_TOKEN] = token
        self._token_str = token

    @property
    def token(self) -> Optional[str]:
        return self._token_str


class _Manager:
    _token: _ManagerToken

    def __init__(self) -> None:
        self._token = _ManagerToken()
        self._setup()

    def _setup(self):
        self._token.probe()
        if not self._token.token:
            self._token.configure()
            self._setup_parent()
        else:
            self._setup_child()

    def _setup_parent(self):
        # TODO(jhr): spin up manager grpc server
        self._atexit_setup()

    def _setup_child(self):
        # TODO(jhr): connect to manager grpc server
        pass

    def _atexit_setup(self):
        print(
            "%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%% atexit register", file=sys.stderr
        )
        atexit.register(lambda: self._atexit_teardown())

    def _atexit_teardown(self):
        print("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%% atexit cleanup", file=sys.stderr)

    def _teardown(self):
        pass
