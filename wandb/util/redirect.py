# -*- coding: utf-8 -*-
"""
util/redirect.
"""

import os
import threading
import sys
import logging


logger = logging.getLogger("wandb")

_LAST_WRITE_TOKEN = "L@stWr!t3T0k3n\n"

class Unbuffered(object):
   def __init__(self, stream):
       self.stream = stream
   def write(self, data):
       self.stream.write(data)
       self.stream.flush()
   def writelines(self, datas):
       self.stream.writelines(datas)
       self.stream.flush()
   def __getattr__(self, attr):
       return getattr(self.stream, attr)


def _pipe_relay(stopped, fd, name, cb, tee):
    while True:
        try:
            data = os.read(fd, 1000)
        except OSError as e:
            # TODO(jhr): handle this
            return
        if len(data) == 0:
            break
        if stopped.isSet():
            # TODO(jhr): Is this going to capture all timings?
            if data.endswith(_LAST_WRITE_TOKEN.encode()):
                logger.info("relay done saw last write: %s", name)
                break
        if tee:
            os.write(tee, data)
        if cb:
            cb(name, data)
    logger.info("relay done done: %s", name)


class Redirect(object):
    def __init__(self, src, dest, unbuffered=False, tee=False):
        self._installed = False
        self._stream = src
        self._dest = dest
        self._unbuffered = unbuffered
        self._tee = tee

        self._old_fd = None
        self._old_fp = None

    def _redirect(self, to_fd, unbuffered=False):
        fp = getattr(sys, self._stream)
        # FIXME(jhr): does this still work under windows?  are we leaking a fd?
        # Do not close old filedescriptor as others might be using it
        # fp.close()
        os.dup2(to_fd, self._old_fd)
        setattr(sys, self._stream, os.fdopen(self._old_fd, 'w'))
        if unbuffered:
            setattr(sys, self._stream, Unbuffered(getattr(sys, self._stream)))

    def install(self):
        logger.info("install start")

        fp = getattr(sys, self._stream)
        fd = fp.fileno()
        old_fp = os.fdopen(os.dup(fd), 'w')

        if self._tee:
            self._dest._set_tee(old_fp.fileno())
        self._dest._start()
        self._installed = True

        self._old_fd = fd
        self._old_fp = old_fp

        self._redirect(to_fd=self._dest._get_writer(), unbuffered=self._unbuffered)
        logger.info("install stop")

    def uninstall(self):
        logger.info("uninstall start")
        self._redirect(to_fd=self._old_fp.fileno())
        self._dest._stop()
        logger.info("uninstall done")


class Capture(object):
    def __init__(self, name, cb):
        self._started = False
        self._name = name
        self._cb = cb
        self._stopped = None
        self._thread = None
        self._tee = None

        self._pipe_rd = None
        self._pipe_wr = None

    def _get_writer(self):
        assert self._started
        return self._pipe_wr

    def _set_tee(self, tee):
        self._tee = tee

    def _start(self):
        rd, wr = os.pipe()
        self._pipe_rd = rd
        self._pipe_wr = wr
        self._started = True

        self._stopped = threading.Event()
        # NB: daemon thread is used because we use atexit to determine when a user process is finished.  the atexit handler is responsible for flushing, joining, and closing
        read_thread = threading.Thread(name=self._name, target=_pipe_relay, args=(self._stopped, self._pipe_rd, self._name, self._cb, self._tee))
        read_thread.daemon = True
        read_thread.start()
        self._thread = read_thread

    def _stop(self):
        name = self._name
        logger.info("_stop: %s", name)

        self._stopped.set()
        os.write(self._pipe_wr, _LAST_WRITE_TOKEN.encode())
        os.close(self._pipe_wr)

        logger.info("_stop closed: %s", name)
        # FIXME: need to shut this down cleanly since it is a daemon thread
        self._thread.join(timeout=30)
        if self._thread.isAlive():
            logger.error("Thread did not join: %s", self._name)
            # TODO(jhr): do something better
        logger.info("_stop joined: %s", name)
        os.close(self._pipe_rd)
        logger.info("_stop rd closed: %s", name)
