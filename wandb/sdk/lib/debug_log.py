"""debug_log

Functions:
    log_record
    log_request
    log_result
    log_response

"""

import datetime
import threading
from typing import cast
from typing import Optional
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import multiprocessing
    import queue
    import socket
    from typing import Union
    from wandb.proto import wandb_internal_pb2 as pb
    from wandb.proto import wandb_server_pb2 as spb

    MessageType = Union[pb.Record, pb.Result, spb.ServerRequest, spb.ServerResponse]
    QueueType = Union[multiprocessing.Queue, queue.Queue]
    TransportType = Union[socket.socket, str]


def _log(
    msg_type: str,
    is_response: bool = False,
    record: "pb.Record" = None,
    result: "pb.Result" = None,
) -> None:
    tname = threading.currentThread().getName()
    now = datetime.datetime.now()
    ts = now.strftime("%H%M%S.%f")
    arrow = "<-" if is_response else "->"
    uuid = "-" * 32
    data = record or result
    if data:
        uuid = data.uuid or uuid
    relay = "-" * 32
    if data and data.control and data.control.relay_id:
        relay = data.control.relay_id
    print(f"{arrow} {ts} {uuid} {relay} {tname} {msg_type}")


def _log_message(msg: "MessageType") -> None:
    record: Optional["pb.Record"] = None
    result: Optional["pb.Result"] = None
    is_response = False
    msg_type: str
    # Note: using strings to avoid an import
    message_type_str = type(msg).__name__
    if message_type_str == "Record":
        record = cast("pb.Record", msg)
        msg_type = str(record.WhichOneof("record_type"))
    elif message_type_str == "Result":
        result = cast("pb.Result", msg)
        msg_type = str(result.WhichOneof("result_type"))
        is_response = True
    elif message_type_str == "ServerRequest":
        server_request = cast("spb.ServerRequest", msg)
        msg_type = str(server_request.WhichOneof("server_request_type"))
    elif message_type_str == "ServerResponse":
        server_response = cast("spb.ServerResponse", msg)
        msg_type = str(server_response.WhichOneof("server_response_type"))
        is_response = True
    else:
        raise AssertionError(f"Unknown message type {message_type_str}")
    _log(msg_type, is_response=is_response, record=record, result=result)


def _log_message_queue(msg: "MessageType", q: "QueueType") -> None:
    _log_message(msg)


def _log_message_dequeue(msg: "MessageType", q: "QueueType") -> None:
    _log_message(msg)


def _log_message_send(msg: "MessageType", t: "TransportType") -> None:
    _log_message(msg)


def _log_message_recv(msg: "MessageType", t: "TransportType") -> None:
    _log_message(msg)


def _log_message_process(msg: "MessageType") -> None:
    _log_message(msg)


def _log_message_link(src: "MessageType", dest: "MessageType") -> None:
    _log_message(src)
    _log_message(dest)


def _log_message_assert(msg: "MessageType") -> None:
    _log_message(msg)


def log_message_queue(msg: "MessageType", q: "QueueType") -> None:
    return None


def log_message_dequeue(msg: "MessageType", q: "QueueType") -> None:
    return None


def log_message_send(msg: "MessageType", t: "TransportType") -> None:
    return None


def log_message_recv(msg: "MessageType", t: "TransportType") -> None:
    return None


def log_message_process(msg: "MessageType") -> None:
    return None


def log_message_link(src: "MessageType", dest: "MessageType") -> None:
    return None


def log_message_assert(msg: "MessageType") -> None:
    return None


def enable() -> None:
    global log_message_queue
    global log_message_dequeue
    global log_message_send
    global log_message_recv
    global log_message_process
    global log_message_link
    global log_message_assert
    log_message_queue = _log_message_queue
    log_message_dequeue = _log_message_dequeue
    log_message_send = _log_message_send
    log_message_recv = _log_message_recv
    log_message_process = _log_message_process
    log_message_link = _log_message_link
    log_message_assert = _log_message_assert


# Uncomment to force enable
# enable()
