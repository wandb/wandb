"""Manage wandb processes.

Create a grpc manager channel.
"""

import atexit
import multiprocessing
import os
from typing import Callable, Optional, Tuple, TYPE_CHECKING

from wandb import env
from wandb.sdk.lib.exit_hooks import ExitHooks

if TYPE_CHECKING:
    from wandb.sdk.service import service
    from wandb.sdk.wandb_settings import Settings


class _ManagerToken:
    _token_str: Optional[str]

    def __init__(self) -> None:
        self._token_str = None

    def probe(self) -> None:
        token = os.environ.get(env.SERVICE)
        if not token:
            return
        self._token_str = token

    def configure(self, port: int) -> None:
        version = "1"
        pid = os.getpid()
        token = "-".join([version, str(pid), str(port)])
        os.environ[env.SERVICE] = token
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
    _atexit_lambda: Optional[Callable[[], None]]
    _hooks: Optional[ExitHooks]

    def __init__(self) -> None:
        # TODO: warn if user doesnt have grpc installed
        from wandb.sdk.service import service

        self._atexit_lambda = None
        self._hooks = None

        self._token = _ManagerToken()
        self._service = service._Service()
        self._setup_mp()
        self._setup()

    def _setup_mp(self) -> None:
        # NOTE: manager does not support fork yet, support coming later
        start_method = multiprocessing.get_start_method(allow_none=True)
        assert start_method != "fork", "start method 'fork' is not supported yet"
        if start_method is None:
            multiprocessing.set_start_method("spawn")

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
        self._atexit_lambda = lambda: self._atexit_teardown()

        self._hooks = ExitHooks()
        self._hooks.hook()
        atexit.register(self._atexit_lambda)

    def _atexit_teardown(self) -> None:
        exit_code = self._hooks.exit_code if self._hooks else 0
        self._teardown(exit_code)

    def _teardown(self, exit_code: int) -> None:
        if self._atexit_lambda:
            atexit.unregister(self._atexit_lambda)
            self._atexit_lambda = None
        self._inform_teardown(exit_code)

    def _get_service(self) -> "service._Service":
        return self._service

    def _inform_init(self, settings: "Settings", run_id: str) -> None:
        svc = self._service
        assert svc
        svc._svc_inform_init(settings=settings, run_id=run_id)

    def _inform_attach(self, attach_id: str) -> None:
        svc = self._service
        assert svc
        svc._svc_inform_attach(attach_id=attach_id)

    def _inform_finish(self, run_id: str = None) -> None:
        svc = self._service
        assert svc
        svc._svc_inform_finish(run_id=run_id)

    def _inform_teardown(self, exit_code: int) -> None:
        svc = self._service
        assert svc
        svc._svc_inform_teardown(exit_code)
