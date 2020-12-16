#
# -*- coding: utf-8 -*-
"""Internal process.

This module implements the entrypoint for the internal process. The internal process
is responsible for handling "record" requests, and responding with "results". Data is
passed to thee process over multiprocessing queues.

Threads:
    HandlerThread -- read from record queue and call handlers
    SenderThread -- send to network
    WriterThread -- write to disk

"""

from __future__ import print_function

import atexit
import logging
import os
import sys
import threading
import time
import traceback

import psutil  # type: ignore
from six.moves import queue
import wandb
from wandb.util import sentry_exc

from . import handler
from . import internal_util
from . import sender
from . import settings_static
from . import writer
from ..interface import interface


logger = logging.getLogger(__name__)


def wandb_internal(settings, record_q, result_q):
    """Internal process function entrypoint.

    Read from record queue and dispatch work to various threads.

    Arguments:
        settings: dictionary of configuration parameters.
        record_q: records to be handled
        result_q: for sending results back

    """
    # mark this process as internal
    wandb._IS_INTERNAL_PROCESS = True

    # Lets make sure we dont modify settings so use a static object
    settings = settings_static.SettingsStatic(settings)
    if settings.log_internal:
        configure_logging(settings.log_internal, settings._log_level)

    parent_pid = os.getppid()
    pid = os.getpid()

    logger.info("W&B internal server running at pid: %s", pid)

    publish_interface = interface.BackendSender(record_q=record_q)

    stopped = threading.Event()
    threads = []

    send_record_q = queue.Queue()
    record_sender_thread = SenderThread(
        settings=settings,
        record_q=send_record_q,
        result_q=result_q,
        stopped=stopped,
        interface=publish_interface,
    )
    threads.append(record_sender_thread)

    write_record_q = queue.Queue()
    record_writer_thread = WriterThread(
        settings=settings,
        record_q=write_record_q,
        result_q=result_q,
        stopped=stopped,
        writer_q=write_record_q,
    )
    threads.append(record_writer_thread)

    record_handler_thread = HandlerThread(
        settings=settings,
        record_q=record_q,
        result_q=result_q,
        stopped=stopped,
        sender_q=send_record_q,
        writer_q=write_record_q,
        interface=publish_interface,
    )
    threads.append(record_handler_thread)

    process_check = ProcessCheck(settings=settings, pid=parent_pid)

    for thread in threads:
        thread.start()

    interrupt_count = 0
    while not stopped.isSet():
        try:
            # wait for stop event
            while not stopped.isSet():
                time.sleep(1)
                if process_check.is_dead():
                    logger.error("Internal process shutdown.")
                    stopped.set()
        except KeyboardInterrupt:
            interrupt_count += 1
            logger.warning("Internal process interrupt: {}".format(interrupt_count))
        finally:
            if interrupt_count >= 2:
                logger.error("Internal process interrupted.")
                stopped.set()

    for thread in threads:
        thread.join()

    for thread in threads:
        exc_info = thread.get_exception()
        if exc_info:
            logger.error("Thread {}:".format(thread.name), exc_info=exc_info)
            print("Thread {}:".format(thread.name), file=sys.stderr)
            traceback.print_exception(*exc_info)
            sentry_exc(exc_info, delay=True)
            sys.exit(-1)


@atexit.register
def handle_exit(*args):
    logger.info("Internal process exited")


def configure_logging(log_fname, log_level, run_id=None):
    # TODO: we may want make prints and stdout make it into the logs
    # sys.stdout = open(settings.log_internal, "a")
    # sys.stderr = open(settings.log_internal, "a")
    logging.root.handlers = []
    log_handler = logging.FileHandler(log_fname)
    log_handler.setLevel(log_level)

    class WBFilter(logging.Filter):
        def filter(self, record):
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
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(log_handler)


class HandlerThread(internal_util.RecordLoopThread):
    """Read records from queue and dispatch to handler routines."""

    def __init__(
        self, settings, record_q, result_q, stopped, sender_q, writer_q, interface
    ):
        super(HandlerThread, self).__init__(
            input_record_q=record_q, result_q=result_q, stopped=stopped,
        )
        self.name = "HandlerThread"
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._stopped = stopped
        self._sender_q = sender_q
        self._writer_q = writer_q
        self._interface = interface

    def _setup(self):
        self._hm = handler.HandleManager(
            settings=self._settings,
            record_q=self._record_q,
            result_q=self._result_q,
            stopped=self._stopped,
            sender_q=self._sender_q,
            writer_q=self._writer_q,
            interface=self._interface,
        )

    def _process(self, record):
        self._hm.handle(record)

    def _finish(self):
        self._hm.finish()


class SenderThread(internal_util.RecordLoopThread):
    """Read records from queue and dispatch to sender routines."""

    def __init__(
        self, settings, record_q, result_q, stopped, interface,
    ):
        super(SenderThread, self).__init__(
            input_record_q=record_q, result_q=result_q, stopped=stopped,
        )
        self.name = "SenderThread"
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._interface = interface

    def _setup(self):
        self._sm = sender.SendManager(
            settings=self._settings,
            record_q=self._record_q,
            result_q=self._result_q,
            interface=self._interface,
        )

    def _process(self, record):
        self._sm.send(record)

    def _finish(self):
        self._sm.finish()


class WriterThread(internal_util.RecordLoopThread):
    """Read records from queue and dispatch to writer routines."""

    def __init__(self, settings, record_q, result_q, stopped, writer_q):
        super(WriterThread, self).__init__(
            input_record_q=writer_q, result_q=result_q, stopped=stopped,
        )
        self.name = "WriterThread"
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q

    def _setup(self):
        self._wm = writer.WriteManager(
            settings=self._settings, record_q=self._record_q, result_q=self._result_q,
        )

    def _process(self, record):
        self._wm.write(record)

    def _finish(self):
        self._wm.finish()


class ProcessCheck(object):
    """Class to help watch a process id to detect when it is dead."""

    def __init__(self, settings, pid):
        self.settings = settings
        self.pid = pid
        self.check_process_last = None
        self.check_process_interval = settings._internal_check_process

    def is_dead(self):
        if not self.check_process_interval:
            return
        time_now = time.time()
        if (
            self.check_process_last
            and time_now < self.check_process_last + self.check_process_interval
        ):
            return
        self.check_process_last = time_now

        exists = psutil.pid_exists(self.pid)
        if not exists:
            logger.warning(
                "Internal process exiting, parent pid {} disappeared".format(self.pid)
            )
            return True
        return False
