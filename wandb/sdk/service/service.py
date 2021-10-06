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

    def __init__(self) -> None:
        self._stub = None

    def _grpc_wait_for_port(
        self, fname: str, proc: subprocess.Popen = None
    ) -> Optional[int]:
        time_max = time.time() + 30
        port = None
        while time.time() < time_max:
            if proc and proc.poll():
                # process finished
                print("proc exited with", proc.returncode)
                return None
            if not os.path.isfile(fname):
                time.sleep(0.2)
                continue
            try:
                f = open(fname)
                port = int(f.read())
            except Exception as e:
                print("Error:", e)
            return port
        return None

    def _grpc_launch_server(self) -> Optional[int]:
        """Launch grpc server and return port."""

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
            internal_proc = subprocess.Popen(
                exec_cmd_list
                + [
                    "wandb",
                    "service",
                    "--port-filename",
                    fname,
                    "--pid",
                    pid_str,
                    "--debug",
                    "true",
                ],
                env=os.environ,
                **kwargs,
            )
            port = self._grpc_wait_for_port(fname, proc=internal_proc)

        return port

    def start(self) -> Optional[int]:
        port = self._grpc_launch_server()
        return port

    def connect(self, port: int) -> None:
        channel = grpc.insecure_channel("localhost:{}".format(port))
        stub = pbgrpc.InternalServiceStub(channel)
        self._stub = stub
        # TODO: make sure service is up

    def _get_stub(self) -> Optional[pbgrpc.InternalServiceStub]:
        return self._stub

    def _svc_inform_init(self, settings: Settings, run_id: str) -> None:
        assert self._stub

        inform_init = spb.ServerInformInitRequest()
        settings_dict = dict(settings)
        settings_dict["_log_level"] = logging.DEBUG
        _pbmap_apply_dict(inform_init._settings_map, settings_dict)
        inform_init._info.stream_id = run_id
        _ = self._stub.ServerInformInit(inform_init)

    def _svc_inform_finish(self, run_id: str = None) -> None:
        assert self._stub
        assert run_id
        inform_fin = spb.ServerInformFinishRequest()
        inform_fin._info.stream_id = run_id
        _ = self._stub.ServerInformFinish(inform_fin)

    def _svc_inform_attach(self, attach_id: str) -> None:
        assert self._stub

        inform_attach = spb.ServerInformAttachRequest()
        inform_attach._info.stream_id = attach_id
        _ = self._stub.ServerInformAttach(inform_attach)

    def _svc_inform_teardown(self, exit_code: int) -> None:
        assert self._stub
        inform_fin = spb.ServerInformTeardownRequest(exit_code=exit_code)
        _ = self._stub.ServerInformTeardown(inform_fin)
