"""wandb library."""

__version__ = "0.0.1.dev1+exp.py"

import datetime
import os
import pathlib
import secrets
import string
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, List, Optional

    from wandb import mailbox

from wandb.proto import wandb_internal_pb2 as pb2
from wandb.proto import wandb_server_pb2 as spb
from wandb.proto import wandb_settings_pb2 as setpb


class MessageRouterClosedError(Exception):
    """Socket has been closed."""


def generate_id(length: int = 8) -> str:
    """Generate a random base-36 string of `length` digits."""
    # There are ~2.8T base-36 8-digit strings. If we generate 210k ids,
    # we'll have a ~1% chance of collision.
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Api:
    def __init__(self):
        self._obj = None

    @property
    def _api(self):
        return self._obj

    def new_session(self) -> "Session":
        return Session(_api=self)

    def teardown(self):
        pass


def new_api():
    return Api()


class Image:
    def __init__(self, data):
        self._data = data


# global library object
default_api = new_api()
default_session = None
default_entity = None
default_project = None
default_group = None
default_run = None


class Session:
    def __init__(self, _api):
        self.__api = _api
        self._loaded = False
        self._last_run = None

    @property
    def _api(self):
        return self.__api._api

    def _ensure_loaded(self):
        if self._loaded:
            return
        from wandb import service

        s = service._Service(None)
        s.start()
        # self._api.pbSessionSetup()
        self._service = s
        self._loaded = True

    def configure_auth(self):
        self._ensure_loaded()
        pass

    def login(self):
        self._ensure_loaded()
        pass

    def new_run(self) -> "Run":
        self._ensure_loaded()
        run = Run(_session=self)
        run._start()
        self._last_run = run
        return run

    def teardown(self):
        pass


def new_session() -> Session:
    return default_api.new_session()


class Run:
    def __init__(self, _session):
        self._session = _session
        self._run_nexus_id = None
        self._step = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finish()

    @property
    def _api(self):
        return self._session._api

    def log(self, data):
        data_msg = pb2.HistoryRecord()
        data_msg.step.num = self._step
        self._step += 1
        for k, v in data.items():
            item = data_msg.item.add()
            item.key = k
            d = pb2.DataValue()
            if isinstance(v, int):
                d.value_int = v
            elif isinstance(v, float):
                d.value_double = v
            elif isinstance(v, str):
                d.value_string = v
            elif isinstance(v, Image):
                tensor_msg = pb2.TensorData()
                tensor_msg.tensor_content = v._data.tobytes()
                tensor_msg.shape.extend(v._data.shape)
                # TODO: see if we can do this without the CopyFrom
                d.value_tensor.CopyFrom(tensor_msg)
            # TODO: see if we can do this without the CopyFrom
            item.value_data.CopyFrom(d)

        # _ = data_msg.SerializeToString()
        # self._api.pbRunLog(self._run_nexus_id, data_bytes, len(data_bytes))
        record = pb2.Record()
        record.history.CopyFrom(data_msg)
        record._info.stream_id = self._run_id
        self._sock_client.send_record_publish(record)

    def _read_message(self) -> "Optional[pb2.Result]":
        from wandb import sock_client

        try:
            resp = self._sock_client.read_server_response(timeout=1)
        except sock_client.SockClientClosedError:
            raise MessageRouterClosedError
        if not resp:
            return None
        msg = resp.result_communicate
        return msg

    def message_loop(self) -> None:
        while not self._join_event.is_set():
            try:
                msg = self._read_message()
            except EOFError:
                # logger.warning("EOFError seen in message_loop")
                pass
            except MessageRouterClosedError:
                break
            if not msg:
                continue
            self._handle_msg_rcv(msg)

    def _handle_msg_rcv(self, msg):
        # print("GOT", msg)
        self._mailbox.deliver(msg)
        pass

    def _socket_router_start(self):
        from wandb import mailbox

        self._mailbox = mailbox.Mailbox()
        self._join_event = threading.Event()
        self._thread = threading.Thread(target=self.message_loop)
        self._thread.name = "MsgRouterThr"
        self._thread.daemon = True
        self._thread.start()

    def _socket_connect(self):
        from wandb import sock_client

        port = self._session._service.sock_port
        self._sock_client = sock_client.SockClient()
        self._sock_client.connect(port)
        # TODO: start a reader thread

        self._socket_router_start()

    def _deliver_record(self, record: "pb2.Record") -> "mailbox.MailboxHandle":
        handle = self._mailbox.get_handle()
        # handle._interface = interface
        # handle._keepalive = self._keepalive
        record.control.mailbox_slot = handle.address
        try:
            # print("SEND", record)
            self._sock_client.send_record_publish(record)
            # interface._publish(record)
        except Exception:
            # interface._transport_mark_failed()
            raise
        # interface._transport_mark_success()
        return handle

    def _start(self):
        # print("start", port)

        self._socket_connect()
        # self._run_nexus_id = self._api.pbRunStart()

        run_id = generate_id()
        settings = setpb.Settings()
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        wandb_dir = "wandb"
        run_mode = "run"
        sync_dir = pathlib.Path(wandb_dir) / (run_mode + "-" + timestamp + "-" + run_id)
        log_dir = sync_dir / "logs"
        files_dir = sync_dir / "files"

        settings.base_url.value = "http://localhost:8080"
        settings.run_id.value = run_id
        settings.sync_dir.value = str(sync_dir)
        settings.sync_file.value = str(sync_dir / ("run-" + run_id + ".wandb"))
        settings.log_internal.value = str(log_dir / "debug-internal.log")
        settings.files_dir.value = str(files_dir)

        settings._file_stream_retry_max.value = 1445
        settings._file_stream_retry_wait_min_seconds.value = 2
        settings._file_stream_retry_wait_max_seconds.value = 60
        settings._file_stream_timeout_seconds.value = 180
        settings._file_transfer_retry_max.value = 20
        settings._file_transfer_retry_wait_min_seconds.value = 2
        settings._file_transfer_retry_wait_max_seconds.value = 60

        os.makedirs(sync_dir)
        os.makedirs(log_dir)
        os.makedirs(files_dir)

        inform_init = spb.ServerInformInitRequest()
        inform_init.settings.CopyFrom(settings)
        inform_init._info.stream_id = run_id

        self._sock_client.send(inform_init=inform_init)
        self._run_id = run_id

        run_record = pb2.RunRecord()
        run_record.run_id = run_id
        record = pb2.Record()
        record.run.CopyFrom(run_record)
        record._info.stream_id = run_id
        # record.control.mailbox_slot = "run"
        handle = self._deliver_record(record)
        # self._sock_client.send_record_publish(record)

        result = handle.wait(timeout=180)
        assert result
        print(f"Run: {result.run_result.run.run_id}")

        # start
        inform_start = spb.ServerInformStartRequest()
        inform_start.settings.CopyFrom(settings)
        inform_start._info.stream_id = run_id
        self._sock_client.send(inform_start=inform_start)

        # start2
        start_req = pb2.RunStartRequest()
        start_req.run.CopyFrom(run_record)
        request = pb2.Request()
        request.run_start.CopyFrom(start_req)
        record = pb2.Record()
        record.request.CopyFrom(request)
        record._info.stream_id = run_id
        handle = self._deliver_record(record)
        result = handle.wait(timeout=180)
        assert result

    def _exit(self):
        exit_record = pb2.RunExitRecord()
        record = pb2.Record()
        record.exit.CopyFrom(exit_record)
        record._info.stream_id = self._run_id
        record.control.always_send = True
        handle = self._deliver_record(record)
        result = handle.wait(timeout=300)
        assert result

    def finish(self):
        self._exit()

        # self._api.pbRunFinish(self._run_nexus_id)
        inform_finish = spb.ServerInformFinishRequest()
        inform_finish._info.stream_id = self._run_id
        self._sock_client.send(inform_finish=inform_finish)

    @property
    def id(self):
        pass


# global default session object
default_session = new_session()


# ---
# wandb 0.x Compatibility
# ---


def require(_):
    pass


def setup():
    default_session._ensure_loaded()


def init(*args, **kwargs):
    return default_session.new_run()


def log(*args, **kwargs):
    default_session._last_run.log(*args, **kwargs)


def teardown():
    global _session
    _session = None
