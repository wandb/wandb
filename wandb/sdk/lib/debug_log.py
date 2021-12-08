"""debug_log.

Functions:
    log_message_queue   - message put() to queue
    log_message_dequeue - message get() from queue
    log_message_send    - message sent to socket
    log_message_recv    - message received from socket
    log_message_process - message processed by thread
    log_message_link    - message linked to another mesage
    log_message_assert  - message encountered problem

"""

import datetime
import logging
import sys
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


# Supported modes:
#   logger - debug_log output goes to python logging (default)
#   stdout - debug_log output goes to stdout
#   stderr - debug_log output goes to stderr
debug_log_mode: Optional[str] = "logger"

logger = logging.getLogger(__name__)


def _log(
    msg_type: str,
    log_type: str,
    is_response: bool = False,
    record: "pb.Record" = None,
    result: "pb.Result" = None,
) -> None:
    tname = threading.currentThread().getName()
    now = datetime.datetime.now()
    ts = now.strftime("%H%M%S.%f")
    arrow = "<-" if is_response else "->"
    uuid = ""
    data = record or result
    if data:
        uuid = data.uuid or uuid
    relay = ""
    if data and data.control and data.control.relay_id:
        relay = data.control.relay_id
    line = f"{arrow} {ts} {log_type:7} {tname:16} {msg_type:28} {uuid:32} {relay:32}"
    if debug_log_mode == "stdout":
        print(line, file=sys.__stdout__)
    elif debug_log_mode == "stderr":
        print(line, file=sys.__stderr__)
    elif debug_log_mode == "logger":
        logger.info(line)


def _record_msg_type(record: "pb.Record") -> str:
    msg_type = str(record.WhichOneof("record_type"))
    if msg_type == "request":
        request = record.request
        msg_type = str(request.WhichOneof("request_type"))
    return msg_type


def _result_msg_type(result: "pb.Result") -> str:
    msg_type = str(result.WhichOneof("result_type"))
    if msg_type == "response":
        response = result.response
        msg_type = str(response.WhichOneof("response_type"))
    return msg_type


def _log_message(msg: "MessageType", log_type: str) -> None:
    record: Optional["pb.Record"] = None
    result: Optional["pb.Result"] = None
    is_response = False
    msg_type: str
    # Note: using strings to avoid an import
    message_type_str = type(msg).__name__
    if message_type_str == "Record":
        record = cast("pb.Record", msg)
        msg_type = _record_msg_type(record)
    elif message_type_str == "Result":
        is_response = True
        result = cast("pb.Result", msg)
        msg_type = _result_msg_type(result)
    elif message_type_str == "ServerRequest":
        server_request = cast("spb.ServerRequest", msg)
        msg_type = str(server_request.WhichOneof("server_request_type"))
        if msg_type == "record_publish":
            record = server_request.record_publish
            sub_msg_type = _record_msg_type(record)
            msg_type = f"pub-{sub_msg_type}"
        elif msg_type == "record_communicate":
            record = server_request.record_communicate
            sub_msg_type = _record_msg_type(record)
            msg_type = f"comm-{sub_msg_type}"
        # print("SRV", server_request)
    elif message_type_str == "ServerResponse":
        is_response = True
        server_response = cast("spb.ServerResponse", msg)
        msg_type = str(server_response.WhichOneof("server_response_type"))
        if msg_type == "result_communicate":
            result = server_response.result_communicate
            sub_msg_type = _result_msg_type(result)
            msg_type = f"comm-{sub_msg_type}"
    else:
        raise AssertionError(f"Unknown message type {message_type_str}")
    _log(
        msg_type,
        is_response=is_response,
        record=record,
        result=result,
        log_type=log_type,
    )


def _log_message_queue(msg: "MessageType", q: "QueueType") -> None:
    _log_message(msg, "queue")


def _log_message_dequeue(msg: "MessageType", q: "QueueType") -> None:
    _log_message(msg, "dequeue")


def _log_message_send(msg: "MessageType", t: "TransportType") -> None:
    _log_message(msg, "send")


def _log_message_recv(msg: "MessageType", t: "TransportType") -> None:
    _log_message(msg, "recv")


def _log_message_process(msg: "MessageType") -> None:
    _log_message(msg, "process")


def _log_message_link(src: "MessageType", dest: "MessageType") -> None:
    _log_message(src, "source")
    _log_message(dest, "dest")


def _log_message_assert(msg: "MessageType") -> None:
    _log_message(msg, "assert")


#
# Default functions when logging is disabled
#


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


def enable(log_mode: str = None) -> None:
    global debug_log_mode
    if log_mode:
        debug_log_mode = log_mode

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
