"""grpc service.

Reliably launch and connect to grpc process.
"""

import os
import subprocess
import sys
import time
from typing import Any, Dict, Optional

import grpc
from wandb.proto import wandb_server_pb2 as spb
from wandb.proto import wandb_server_pb2_grpc as pbgrpc


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
        # https://github.com/wandb/client/blob/archive/old-cli/wandb/__init__.py
        # https://stackoverflow.com/questions/1196074/how-to-start-a-background-process-in-python
        # kwargs: Dict[str, Any] = dict(close_fds=True, start_new_session=True)
        kwargs: Dict[str, Any] = dict(close_fds=True)
        # kwargs: Dict[str, Any] = dict()

        # TODO(add processid)
        pid = os.getpid()
        fname = "/tmp/out-{}-port.txt".format(pid)

        try:
            os.unlink(fname)
        except Exception:
            pass

        pid_str = str(os.getpid())
        exec_cmd_list = [sys.executable, "-m"]
        if os.environ.get("COVERAGE_RCFILE"):
            exec_cmd_list += ["coverage", "run", "-m"]
        internal_proc = subprocess.Popen(
            exec_cmd_list
            + [
                "wandb",
                "grpc-server",
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
        try:
            os.unlink(fname)
        except Exception:
            pass

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

    def _svc_inform_init(self, run_id: str = None) -> None:
        assert self._stub
        assert run_id
        inform_init = spb.ServerInformInitRequest()
        inform_init._info.stream_id = run_id
        _ = self._stub.ServerInformInit(inform_init)

    def _svc_inform_finish(self, run_id: str = None) -> None:
        assert self._stub
        assert run_id
        inform_fin = spb.ServerInformFinishRequest()
        inform_fin._info.stream_id = run_id
        _ = self._stub.ServerInformFinish(inform_fin)

    def _svc_inform_teardown(self, exit_code: int) -> None:
        assert self._stub
        inform_fin = spb.ServerInformTeardownRequest(exit_code=exit_code)
        _ = self._stub.ServerInformTeardown(inform_fin)
