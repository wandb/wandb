"""tracelog.

Functions:
    log_message_queue   - message put() to queue
    log_message_dequeue - message get() from queue
    log_message_send    - message sent to socket
    log_message_recv    - message received from socket
    log_message_process - message processed by thread
    log_message_link    - message linked to another message
    log_message_assert  - message encountered problem

"""

import datetime
import logging
import secrets
import sys
import threading
from typing import TYPE_CHECKING, Optional, cast

if TYPE_CHECKING:
    import multiprocessing
    import queue
    import socket
    from typing import Union

    from wandb.proto import wandb_internal_pb2 as pb
    from wandb.proto import wandb_server_pb2 as spb

    MessageQueueType = Union[pb.Record, pb.Result]
    MessageType = Union[pb.Record, pb.Result, spb.ServerRequest, spb.ServerResponse]
    QueueType = Union[multiprocessing.Queue, queue.Queue]
    TransportType = Union[socket.socket, str]


# Supported modes:
#   logger - tracelog output goes to python logging (default)
#   stdout - tracelog output goes to stdout
#   stderr - tracelog output goes to stderr
tracelog_mode: Optional[str] = "logger"

logger = logging.getLogger(__name__)


ANNOTATE_QUEUE_NAME = "_DEBUGLOG_QUEUE_NAME"

# capture stdout and stderr before anyone messes with them
stdout_write = sys.__stdout__.write  # type: ignore
stderr_write = sys.__stderr__.write  # type: ignore


def _log(
    msg_type: str,
    log_type: str,
    is_response: bool = False,
    record: Optional["pb.Record"] = None,
    result: Optional["pb.Result"] = None,
    resource: Optional[str] = None,
) -> None:
    prefix = "TRACELOG(1)"
    tname = threading.current_thread().name
    now = datetime.datetime.now()
    ts = now.strftime("%H%M%S.%f")
    arrow = "<-" if is_response else "->"
    resource = resource or "unknown"
    uuid = ""
    data = record or result
    record_id = ""
    if data:
        uuid = data.uuid or uuid
        record_id = data._info._tracelog_id
    uuid = uuid or "-"
    record_id = record_id or "-"
    relay = ""
    if data and data.control and data.control.relay_id:
        relay = data.control.relay_id
    relay = relay or "-"
    line = f"{prefix} {arrow} {ts} {record_id:16} {log_type:7} {resource:8} {tname:16} {msg_type:32} {uuid:32} {relay:32}"
    if tracelog_mode == "stdout":
        stdout_write(f"{line}\n")
    elif tracelog_mode == "stderr":
        stderr_write(f"{line}\n")
    elif tracelog_mode == "logger":
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


def _log_message(
    msg: "MessageType", log_type: str, resource: Optional[str] = None
) -> None:
    record: Optional[pb.Record] = None
    result: Optional[pb.Result] = None
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
        resource=resource,
    )


def _log_message_queue(msg: "MessageQueueType", q: "QueueType") -> None:
    _annotate_message(msg)
    resource = getattr(q, ANNOTATE_QUEUE_NAME, None)
    _log_message(msg, "queue", resource=resource)


def _log_message_dequeue(msg: "MessageQueueType", q: "QueueType") -> None:
    resource = getattr(q, ANNOTATE_QUEUE_NAME, None)
    _log_message(msg, "dequeue", resource=resource)


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


def _annotate_queue(q: "QueueType", name: str) -> None:
    setattr(q, ANNOTATE_QUEUE_NAME, name)


def _annotate_message(msg: "MessageQueueType") -> None:
    record_id = secrets.token_hex(8)
    msg._info._tracelog_id = record_id


#
# Default functions when logging is disabled
#


def log_message_queue(msg: "MessageQueueType", q: "QueueType") -> None:
    return None


def log_message_dequeue(msg: "MessageQueueType", q: "QueueType") -> None:
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


def annotate_queue(q: "QueueType", name: str) -> None:
    return None


def annotate_message(msg: "MessageQueueType") -> None:
    return None


def enable(log_mode: Optional[str] = None) -> None:
    global tracelog_mode
    if log_mode:
        tracelog_mode = log_mode

    global log_message_queue
    global log_message_dequeue
    global log_message_send
    global log_message_recv
    global log_message_process
    global log_message_link
    global log_message_assert
    global annotate_queue
    global annotate_message
    log_message_queue = _log_message_queue
    log_message_dequeue = _log_message_dequeue
    log_message_send = _log_message_send
    log_message_recv = _log_message_recv
    log_message_process = _log_message_process
    log_message_link = _log_message_link
    log_message_assert = _log_message_assert
    annotate_queue = _annotate_queue
    annotate_message = _annotate_message
