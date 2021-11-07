"""grpc service.

Reliably launch and connect to grpc process.
"""

import datetime
import enum
import logging
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, Optional
from typing import TYPE_CHECKING

import grpc
from wandb.proto import wandb_server_pb2 as spb
from wandb.proto import wandb_server_pb2_grpc as pbgrpc
from wandb.sdk.wandb_settings import Settings

from ..lib.sock_client import SockClient
from . import port_file

if TYPE_CHECKING:
    from google.protobuf.internal.containers import MessageMap


def _pbmap_apply_dict(
    m: "MessageMap[str, spb.SettingsValue]", d: Dict[str, Any]
) -> None:
    for k, v in d.items():
        if isinstance(v, datetime.datetime):
            continue
        if isinstance(v, enum.Enum):
            continue
        sv = spb.SettingsValue()
        if v is None:
            sv.null_value = True
        elif isinstance(v, int):
            sv.int_value = v
        elif isinstance(v, float):
            sv.float_value = v
        elif isinstance(v, str):
            sv.string_value = v
        elif isinstance(v, bool):
            sv.bool_value = v
        elif isinstance(v, tuple):
            sv.tuple_value.string_values.extend(v)
        m[k].CopyFrom(sv)


class _Service:
    _stub: Optional[pbgrpc.InternalServiceStub]
    _use_socket: bool
    _sock_client: Optional[SockClient]
    _grpc_port: Optional[int]
    _sock_port: Optional[int]

    def __init__(self) -> None:
        self._stub = None
        self._use_socket = False
        self._grpc_port = None
        self._sock_port = None

    def _wait_for_ports(self, fname: str, proc: subprocess.Popen = None) -> bool:
        time_max = time.time() + 30
        port = None
        while time.time() < time_max:
            if proc and proc.poll():
                # process finished
                print("proc exited with", proc.returncode)
                return False
            if not os.path.isfile(fname):
                time.sleep(0.2)
                continue
            try:
                pf = port_file.PortFile()
                pf.read(fname)
                if not pf.is_valid:
                    time.sleep(0.2)
                    continue
                self._grpc_port = pf.grpc_port
                self._sock_port = pf.sock_port
            except Exception as e:
                print("Error:", e)
            return False
        return False

    def _launch_server(self) -> None:
        """Launch server and set ports."""

        # References for starting processes
        # - https://github.com/wandb/client/blob/archive/old-cli/wandb/__init__.py
        # - https://stackoverflow.com/questions/1196074/how-to-start-a-background-process-in-python

        kwargs: Dict[str, Any] = dict(close_fds=True)

        pid = os.getpid()

        with tempfile.TemporaryDirectory() as tmpdir:
            fname = os.path.join(tmpdir, f"port-{pid}.txt")

            pid_str = str(os.getpid())
            exec_cmd_list = [sys.executable, "-m"]
            # Add coverage collection if needed
            if os.environ.get("COVERAGE_RCFILE"):
                exec_cmd_list += ["coverage", "run", "-m"]
            service_args = [
                "wandb",
                "service",
                "--port-filename",
                fname,
                "--pid",
                pid_str,
                "--debug",
            ]
            service_args.append("--serve-sock")
            service_args.append("--serve-grpc")
            internal_proc = subprocess.Popen(
                exec_cmd_list + service_args, env=os.environ, **kwargs,
            )
            self._wait_for_ports(fname, proc=internal_proc)

    def start(self) -> None:
        self._use_socket = True
        self._launch_server()

    @property
    def use_socket(self):
        return self._use_socket

    @property
    def grpc_port(self) -> Optional[int]:
        return self._grpc_port

    @property
    def sock_port(self) -> Optional[int]:
        return self._sock_port

    def connect(self, port: int) -> None:
        if self._use_socket:
            print("sc1 port", port)
            self._sock_client = SockClient()
            self._sock_client.connect(port=port)
            return
        print("sc1")
        channel = grpc.insecure_channel("localhost:{}".format(port))
        stub = pbgrpc.InternalServiceStub(channel)
        self._stub = stub
        # TODO: make sure service is up

    def _get_stub(self) -> Optional[pbgrpc.InternalServiceStub]:
        return self._stub

    def _svc_inform_init(self, settings: Settings, run_id: str) -> None:
        inform_init = spb.ServerInformInitRequest()
        settings_dict = dict(settings)
        settings_dict["_log_level"] = logging.DEBUG
        _pbmap_apply_dict(inform_init._settings_map, settings_dict)
        inform_init._info.stream_id = run_id

        if self._use_socket:
            assert self._sock_client
            self._sock_client.send(inform_init=inform_init)
            return

        assert self._stub
        _ = self._stub.ServerInformInit(inform_init)

    def _svc_inform_finish(self, run_id: str = None) -> None:
        assert run_id
        inform_fin = spb.ServerInformFinishRequest()
        inform_fin._info.stream_id = run_id

        if self._use_socket:
            assert self._sock_client
            self._sock_client.send(inform_finish=inform_fin)
            return

        assert self._stub
        _ = self._stub.ServerInformFinish(inform_fin)

    def _svc_inform_attach(self, attach_id: str) -> None:
        assert self._stub

        inform_attach = spb.ServerInformAttachRequest()
        inform_attach._info.stream_id = attach_id
        _ = self._stub.ServerInformAttach(inform_attach)

    def _svc_inform_teardown(self, exit_code: int) -> None:
        inform_teardown = spb.ServerInformTeardownRequest(exit_code=exit_code)

        if self._use_socket:
            assert self._sock_client
            self._sock_client.send(inform_teardown=inform_teardown)
            return

        assert self._stub
        _ = self._stub.ServerInformTeardown(inform_teardown)
