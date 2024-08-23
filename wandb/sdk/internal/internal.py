#
"""Internal process.

This module implements the entrypoint for the internal process. The internal process
is responsible for handling "record" requests, and responding with "results". Data is
passed to the process over multiprocessing queues.

Threads:
    HandlerThread -- read from record queue and call handlers
    SenderThread -- send to network
    WriterThread -- write to disk

"""

import atexit
import logging
import os
import queue
import sys
import threading
import time
import traceback
from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional

import psutil

import wandb

from ..interface.interface_queue import InterfaceQueue
from ..lib import tracelog
from . import context, handler, internal_util, sender, writer

if TYPE_CHECKING:
    from queue import Queue
    from threading import Event

    from wandb.proto.wandb_internal_pb2 import Record, Result

    from .internal_util import RecordLoopThread
    from .settings_static import SettingsStatic


logger = logging.getLogger(__name__)


def wandb_internal(
    settings: "SettingsStatic",
    record_q: "Queue[Record]",
    result_q: "Queue[Result]",
    port: Optional[int] = None,
    user_pid: Optional[int] = None,
) -> None:
    """Internal process function entrypoint.

    Read from record queue and dispatch work to various threads.

    Arguments:
        settings: settings object
        record_q: records to be handled
        result_q: for sending results back

    """
    # mark this process as internal
    wandb._set_internal_process()  # type: ignore
    _setup_tracelog()
    started = time.time()

    # any sentry events in the internal process will be tagged as such
    wandb._sentry.configure_scope(process_context="internal", tags=dict(settings))

    # register the exit handler only when wandb_internal is called, not on import
    @atexit.register
    def handle_exit(*args: "Any") -> None:
        logger.info("Internal process exited")

    # Let's make sure we don't modify settings so use a static object
    _settings = settings
    if _settings.log_internal:
        configure_logging(_settings.log_internal, _settings._log_level)

    user_pid = user_pid or os.getppid()
    pid = os.getpid()

    logger.info(
        "W&B internal server running at pid: %s, started at: %s",
        pid,
        datetime.fromtimestamp(started),
    )

    tracelog.annotate_queue(record_q, "record_q")
    tracelog.annotate_queue(result_q, "result_q")
    publish_interface = InterfaceQueue(record_q=record_q)

    stopped = threading.Event()
    threads: List[RecordLoopThread] = []

    context_keeper = context.ContextKeeper()

    send_record_q: Queue[Record] = queue.Queue()
    tracelog.annotate_queue(send_record_q, "send_q")

    write_record_q: Queue[Record] = queue.Queue()
    tracelog.annotate_queue(write_record_q, "write_q")

    record_sender_thread = SenderThread(
        settings=_settings,
        record_q=send_record_q,
        result_q=result_q,
        stopped=stopped,
        interface=publish_interface,
        debounce_interval_ms=5000,
        context_keeper=context_keeper,
    )
    threads.append(record_sender_thread)

    record_writer_thread = WriterThread(
        settings=_settings,
        record_q=write_record_q,
        result_q=result_q,
        stopped=stopped,
        interface=publish_interface,
        sender_q=send_record_q,
        context_keeper=context_keeper,
    )
    threads.append(record_writer_thread)

    record_handler_thread = HandlerThread(
        settings=_settings,
        record_q=record_q,
        result_q=result_q,
        stopped=stopped,
        writer_q=write_record_q,
        interface=publish_interface,
        context_keeper=context_keeper,
    )
    threads.append(record_handler_thread)

    process_check = ProcessCheck(settings=_settings, user_pid=user_pid)

    for thread in threads:
        thread.start()

    interrupt_count = 0
    while not stopped.is_set():
        try:
            # wait for stop event
            while not stopped.is_set():
                time.sleep(1)
                if process_check.is_dead():
                    logger.error("Internal process shutdown.")
                    stopped.set()
        except KeyboardInterrupt:
            interrupt_count += 1
            logger.warning(f"Internal process interrupt: {interrupt_count}")
        finally:
            if interrupt_count >= 2:
                logger.error("Internal process interrupted.")
                stopped.set()

    for thread in threads:
        thread.join()

    def close_internal_log() -> None:
        root = logging.getLogger("wandb")
        for _handler in root.handlers[:]:
            _handler.close()
            root.removeHandler(_handler)

    for thread in threads:
        exc_info = thread.get_exception()
        if exc_info:
            logger.error(f"Thread {thread.name}:", exc_info=exc_info)
            print(f"Thread {thread.name}:", file=sys.stderr)
            traceback.print_exception(*exc_info)
            wandb._sentry.exception(exc_info)
            wandb.termerror("Internal wandb error: file data was not synced")
            if not settings._disable_service:
                # TODO: We can make this more graceful by returning an error to streams.py
                # and potentially just fail the one stream.
                os._exit(-1)
            sys.exit(-1)

    close_internal_log()


def _setup_tracelog() -> None:
    # TODO: remove this temporary hack, need to find a better way to pass settings
    # to the server.  for now lets just look at the environment variable we need
    tracelog_mode = os.environ.get("WANDB_TRACELOG")
    if tracelog_mode:
        tracelog.enable(tracelog_mode)


def configure_logging(
    log_fname: str, log_level: int, run_id: Optional[str] = None
) -> None:
    # TODO: we may want make prints and stdout make it into the logs
    # sys.stdout = open(settings.log_internal, "a")
    # sys.stderr = open(settings.log_internal, "a")
    log_handler = logging.FileHandler(log_fname)
    log_handler.setLevel(log_level)

    class WBFilter(logging.Filter):
        def filter(self, record: "Any") -> bool:
            record.run_id = run_id
            return True

    if run_id:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d "
            "[%(run_id)s:%(filename)s:%(funcName)s():%(lineno)s] %(message)s"
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d "
            "[%(filename)s:%(funcName)s():%(lineno)s] %(message)s"
        )

    log_handler.setFormatter(formatter)
    if run_id:
        log_handler.addFilter(WBFilter())
    # If this is called without "wandb", backend logs from this module
    # are not streamed to `debug-internal.log` when we spawn with fork
    # TODO: (cvp) we should really take another pass at logging in general
    root = logging.getLogger("wandb")
    root.propagate = False
    root.setLevel(logging.DEBUG)
    root.addHandler(log_handler)


class HandlerThread(internal_util.RecordLoopThread):
    """Read records from queue and dispatch to handler routines."""

    _record_q: "Queue[Record]"
    _result_q: "Queue[Result]"
    _stopped: "Event"
    _context_keeper: context.ContextKeeper

    def __init__(
        self,
        settings: "SettingsStatic",
        record_q: "Queue[Record]",
        result_q: "Queue[Result]",
        stopped: "Event",
        writer_q: "Queue[Record]",
        interface: "InterfaceQueue",
        context_keeper: context.ContextKeeper,
        debounce_interval_ms: "float" = 1000,
    ) -> None:
        super().__init__(
            input_record_q=record_q,
            result_q=result_q,
            stopped=stopped,
            debounce_interval_ms=debounce_interval_ms,
        )
        self.name = "HandlerThread"
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._stopped = stopped
        self._writer_q = writer_q
        self._interface = interface
        self._context_keeper = context_keeper

    def _setup(self) -> None:
        self._hm = handler.HandleManager(
            settings=self._settings,
            record_q=self._record_q,
            result_q=self._result_q,
            stopped=self._stopped,
            writer_q=self._writer_q,
            interface=self._interface,
            context_keeper=self._context_keeper,
        )

    def _process(self, record: "Record") -> None:
        self._hm.handle(record)

    def _finish(self) -> None:
        self._hm.finish()

    def _debounce(self) -> None:
        self._hm.debounce()


class SenderThread(internal_util.RecordLoopThread):
    """Read records from queue and dispatch to sender routines."""

    _record_q: "Queue[Record]"
    _result_q: "Queue[Result]"
    _context_keeper: context.ContextKeeper

    def __init__(
        self,
        settings: "SettingsStatic",
        record_q: "Queue[Record]",
        result_q: "Queue[Result]",
        stopped: "Event",
        interface: "InterfaceQueue",
        context_keeper: context.ContextKeeper,
        debounce_interval_ms: "float" = 5000,
    ) -> None:
        super().__init__(
            input_record_q=record_q,
            result_q=result_q,
            stopped=stopped,
            debounce_interval_ms=debounce_interval_ms,
        )
        self.name = "SenderThread"
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._interface = interface
        self._context_keeper = context_keeper

    def _setup(self) -> None:
        self._sm = sender.SendManager(
            settings=self._settings,
            record_q=self._record_q,
            result_q=self._result_q,
            interface=self._interface,
            context_keeper=self._context_keeper,
        )

    def _process(self, record: "Record") -> None:
        self._sm.send(record)

    def _finish(self) -> None:
        self._sm.finish()

    def _debounce(self) -> None:
        self._sm.debounce()


class WriterThread(internal_util.RecordLoopThread):
    """Read records from queue and dispatch to writer routines."""

    _record_q: "Queue[Record]"
    _result_q: "Queue[Result]"
    _context_keeper: context.ContextKeeper

    def __init__(
        self,
        settings: "SettingsStatic",
        record_q: "Queue[Record]",
        result_q: "Queue[Result]",
        stopped: "Event",
        interface: "InterfaceQueue",
        sender_q: "Queue[Record]",
        context_keeper: context.ContextKeeper,
        debounce_interval_ms: "float" = 1000,
    ) -> None:
        super().__init__(
            input_record_q=record_q,
            result_q=result_q,
            stopped=stopped,
            debounce_interval_ms=debounce_interval_ms,
        )
        self.name = "WriterThread"
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._sender_q = sender_q
        self._interface = interface
        self._context_keeper = context_keeper

    def _setup(self) -> None:
        self._wm = writer.WriteManager(
            settings=self._settings,
            record_q=self._record_q,
            result_q=self._result_q,
            sender_q=self._sender_q,
            interface=self._interface,
            context_keeper=self._context_keeper,
        )

    def _process(self, record: "Record") -> None:
        self._wm.write(record)

    def _finish(self) -> None:
        self._wm.finish()

    def _debounce(self) -> None:
        self._wm.debounce()


class ProcessCheck:
    """Class to help watch a process id to detect when it is dead."""

    check_process_last: Optional[float]

    def __init__(self, settings: "SettingsStatic", user_pid: Optional[int]) -> None:
        self.settings = settings
        self.pid = user_pid
        self.check_process_last = None
        self.check_process_interval = settings._internal_check_process

    def is_dead(self) -> bool:
        if not self.check_process_interval or not self.pid:
            return False
        time_now = time.time()
        if (
            self.check_process_last
            and time_now < self.check_process_last + self.check_process_interval
        ):
            return False
        self.check_process_last = time_now

        # TODO(jhr): check for os.getppid on unix being 1?
        exists = psutil.pid_exists(self.pid)
        if not exists:
            logger.warning(
                f"Internal process exiting, parent pid {self.pid} disappeared"
            )
            return True
        return False
