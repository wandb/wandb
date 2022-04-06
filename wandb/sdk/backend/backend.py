"""Backend - Send to internal process

Manage backend.

"""

import importlib.machinery
import logging
import multiprocessing
import os
import sys
import threading
from typing import Any, Callable, Dict, Optional
from typing import cast
from typing import TYPE_CHECKING

import wandb

from ..interface.interface import InterfaceBase
from ..interface.interface_queue import InterfaceQueue
from ..internal.internal import wandb_internal
from ..wandb_manager import _Manager
from ..wandb_settings import Settings


if TYPE_CHECKING:
    from ..wandb_run import Run
    from wandb.proto.wandb_internal_pb2 import Record, Result
    from ..service.service_grpc import ServiceGrpcInterface
    from ..service.service_sock import ServiceSockInterface

logger = logging.getLogger("wandb")


class BackendThread(threading.Thread):
    """Class to running internal process as a thread."""

    def __init__(self, target: Callable, kwargs: Dict[str, Any]) -> None:
        threading.Thread.__init__(self)
        self.name = "BackendThr"
        self._target = target
        self._kwargs = kwargs
        self.daemon = True
        self.pid = 0

    def run(self) -> None:
        self._target(**self._kwargs)


class Backend:
    # multiprocessing context or module
    _multiprocessing: multiprocessing.context.BaseContext
    interface: Optional[InterfaceBase]
    _internal_pid: Optional[int]
    wandb_process: Optional[multiprocessing.process.BaseProcess]
    _settings: Optional[Settings]
    record_q: Optional["multiprocessing.Queue[Record]"]
    result_q: Optional["multiprocessing.Queue[Result]"]

    def __init__(
        self, settings: Settings = None, log_level: int = None, manager: _Manager = None
    ) -> None:
        self._done = False
        self.record_q = None
        self.result_q = None
        self.wandb_process = None
        self.interface = None
        self._internal_pid = None
        self._settings = settings
        self._log_level = log_level
        self._manager = manager

        self._multiprocessing = multiprocessing  # type: ignore
        self._multiprocessing_setup()

        # for _module_main_* methods
        self._save_mod_path: Optional[str] = None
        self._save_mod_spec = None

    def _hack_set_run(self, run: "Run") -> None:
        assert self.interface
        self.interface._hack_set_run(run)

    def _multiprocessing_setup(self) -> None:
        assert self._settings
        if self._settings.start_method == "thread":
            return

        # defaulting to spawn for now, fork needs more testing
        start_method = self._settings.start_method or "spawn"

        # TODO: use fork context if unix and frozen?
        # if py34+, else fall back
        if not hasattr(multiprocessing, "get_context"):
            return
        all_methods = multiprocessing.get_all_start_methods()
        logger.info(
            "multiprocessing start_methods={}, using: {}".format(
                ",".join(all_methods), start_method
            )
        )
        ctx = multiprocessing.get_context(start_method)
        self._multiprocessing = ctx

    def _module_main_install(self) -> None:
        # Support running code without a: __name__ == "__main__"
        main_module = sys.modules["__main__"]
        main_mod_spec = getattr(main_module, "__spec__", None)
        main_mod_path = getattr(main_module, "__file__", None)
        if main_mod_spec is None:  # hack for pdb
            # Note: typing has trouble with BuiltinImporter
            loader: "Loader" = importlib.machinery.BuiltinImporter  # type: ignore # noqa: F821
            main_mod_spec = importlib.machinery.ModuleSpec(
                name="wandb.mpmain", loader=loader
            )
            main_module.__spec__ = main_mod_spec
        else:
            self._save_mod_spec = main_mod_spec

        if main_mod_path is not None:
            self._save_mod_path = main_module.__file__
            fname = os.path.join(
                os.path.dirname(wandb.__file__), "mpmain", "__main__.py"
            )
            main_module.__file__ = fname

    def _module_main_uninstall(self) -> None:
        main_module = sys.modules["__main__"]
        # Undo temporary changes from: __name__ == "__main__"
        main_module.__spec__ = self._save_mod_spec
        if self._save_mod_path:
            main_module.__file__ = self._save_mod_path

    def _ensure_launched_manager(self) -> None:
        # grpc_port: Optional[int] = None
        # attach_id = self._settings._attach_id if self._settings else None
        # if attach_id:
        #     # TODO(attach): implement
        #     # already have a server, assume it is already up
        #     grpc_port = int(attach_id)

        assert self._manager
        svc = self._manager._get_service()
        assert svc
        svc_iface = svc.service_interface

        svc_transport = svc_iface.get_transport()
        if svc_transport == "tcp":
            from ..interface.interface_sock import InterfaceSock

            svc_iface_sock = cast("ServiceSockInterface", svc_iface)
            sock_client = svc_iface_sock._get_sock_client()
            sock_interface = InterfaceSock(sock_client)
            self.interface = sock_interface
        elif svc_transport == "grpc":
            from ..interface.interface_grpc import InterfaceGrpc

            svc_iface_grpc = cast("ServiceGrpcInterface", svc_iface)
            stub = svc_iface_grpc._get_stub()
            grpc_interface = InterfaceGrpc()
            grpc_interface._connect(stub=stub)
            self.interface = grpc_interface
        else:
            raise AssertionError(f"Unsupported service transport: {svc_transport}")

    def ensure_launched(self) -> None:
        """Launch backend worker if not running."""
        settings: Dict[str, Any] = dict()
        if self._settings is not None:
            settings = self._settings.make_static()

        settings["_log_level"] = self._log_level or logging.DEBUG

        # TODO: this is brittle and should likely be handled directly on the
        #  settings object. Multi-processing blows up when it can't pickle
        #  objects.
        if "_early_logger" in settings:
            del settings["_early_logger"]

        start_method = settings.get("start_method")

        if self._manager:
            self._ensure_launched_manager()
            return

        self.record_q = self._multiprocessing.Queue()
        self.result_q = self._multiprocessing.Queue()
        user_pid = os.getpid()

        if start_method == "thread":
            wandb._set_internal_process(disable=True)  # type: ignore
            wandb_thread = BackendThread(
                target=wandb_internal,
                kwargs=dict(
                    settings=settings,
                    record_q=self.record_q,
                    result_q=self.result_q,
                    user_pid=user_pid,
                ),
            )
            # TODO: risky cast, assumes BackendThread Process duck typing
            self.wandb_process = wandb_thread  # type: ignore
        else:
            self.wandb_process = self._multiprocessing.Process(
                target=wandb_internal,
                kwargs=dict(
                    settings=settings,
                    record_q=self.record_q,
                    result_q=self.result_q,
                    user_pid=user_pid,
                ),
            )
            self.wandb_process.name = "wandb_internal"

        self._module_main_install()

        logger.info("starting backend process...")
        # Start the process with __name__ == "__main__" workarounds
        assert self.wandb_process
        self.wandb_process.start()
        self._internal_pid = self.wandb_process.pid
        logger.info(f"started backend process with pid: {self.wandb_process.pid}")

        self._module_main_uninstall()

        self.interface = InterfaceQueue(
            process=self.wandb_process,
            record_q=self.record_q,
            result_q=self.result_q,
        )

    def server_connect(self) -> None:
        """Connect to server."""
        pass

    def server_status(self) -> None:
        """Report server status."""
        pass

    def cleanup(self) -> None:
        # TODO: make _done atomic
        if self._done:
            return
        self._done = True
        if self.interface:
            self.interface.join()
        if self.wandb_process:
            self.wandb_process.join()

        if self.record_q:
            self.record_q.close()
        if self.result_q:
            self.result_q.close()
        # No printing allowed from here until redirect restore!!!
