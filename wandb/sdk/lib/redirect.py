#
# -*- coding: utf-8 -*-
"""
util/redirect.
"""

import io
import logging
import os
import sys
import threading


logger = logging.getLogger("wandb")

_LAST_WRITE_TOKEN = "L@stWr!t3T0k3n\n"


class Unbuffered(object):
    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        try:
            self.stream.write(data)
            self.stream.flush()
        except Exception:
            pass  # Underlying stream might be closed.

    def writelines(self, datas):
        try:
            self.stream.writelines(datas)
            self.stream.flush()
        except Exception:
            pass  # Underlying stream might be closed.

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


class StreamFork(object):
    def __init__(self, output_streams, unbuffered=False):
        self.output_streams = output_streams
        self.unbuffered = unbuffered

    def write(self, data):
        output_streams = object.__getattribute__(self, "output_streams")
        unbuffered = object.__getattribute__(self, "unbuffered")
        for stream in output_streams:
            stream.write(data)
            if unbuffered:
                stream.flush()

    def writelines(self, datas):
        output_streams = object.__getattribute__(self, "output_streams")
        unbuffered = object.__getattribute__(self, "unbuffered")
        for stream in output_streams:
            stream.writelines(datas)
            if unbuffered:
                stream.flush()

    def __getattr__(self, attr):
        output_streams = object.__getattribute__(self, "output_streams")
        return getattr(output_streams[0], attr)


class RedirectBase(object):
    def install(self) -> None:
        raise NotImplementedError

    def uninstall(self) -> None:
        raise NotImplementedError


class StreamWrapper(RedirectBase):
    def __init__(self, name, cb, output_writer=None):
        self.name = name
        self.cb = cb
        self.output_writer = output_writer
        self.stream = getattr(sys, name)
        self.installed = False

    def install(self):
        if self.installed:
            return
        # TODO(farizrahman4u): patch writelines too?
        old_write = self.stream.write
        name = self.name
        cb = self.cb
        output_writer = self.output_writer
        if output_writer is None:

            def new_write(data):
                cb(name, data)
                old_write(data)

        else:

            def new_write(data):
                cb(name, data)
                old_write(data)
                try:
                    output_writer.write(data.encode("utf-8"))
                except Exception as e:
                    logger.error("Error while writing to file :" + str(e))

        self.stream.write = new_write
        self._old_write = old_write
        self.installed = True

    def uninstall(self):
        if self.installed:
            self.stream.write = self._old_write
            self.installed = False


def _pipe_relay(stopped, fd, name, cb, tee, output_writer):
    while True:
        try:
            data = os.read(fd, 4096)
        except OSError:
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
        if output_writer:
            output_writer.write(data)
        if cb:
            try:
                cb(name, data)
            except Exception:
                logger.exception("problem in pipe relay")
                # Prevent further callbacks
                # TODO(jhr): how does error get propogated?
                cb = None
                # exc_info = sys.exc_info()
                # six.reraise(*exc_info)
    logger.info("relay done done: %s", name)


class Redirect(RedirectBase):
    def __init__(self, src, dest, unbuffered=False, tee=False):
        self._installed = False
        self._stream = src
        self._dest = dest
        self._unbuffered = unbuffered
        self._tee = tee

        self._old_fd = None
        self._old_fp = None

        _src = getattr(sys, src)
        if _src != getattr(sys, "__%s__" % src):
            if hasattr(_src, "fileno"):
                try:
                    _src.fileno()
                    self._io_wrapped = False
                except io.UnsupportedOperation:
                    self._io_wrapped = True
            else:
                self._io_wrapped = True
        else:
            self._io_wrapped = False

    def _redirect(self, to_fd, unbuffered=False, close=False):
        if close:
            fp = getattr(sys, self._stream)
            # TODO(jhr): does this still work under windows?  are we leaking a fd?
            # Do not close old filedescriptor as others might be using it
            try:
                fp.close()
            except Exception:
                pass  # Stream might be wrapped by another program which doesn't support closing.
        os.dup2(to_fd, self._old_fd)
        if self._io_wrapped:
            if close:
                setattr(sys, self._stream, getattr(sys, self._stream).output_streams[0])
            else:
                setattr(
                    sys,
                    self._stream,
                    StreamFork(
                        [getattr(sys, self._stream), os.fdopen(self._old_fd, "w")],
                        unbuffered=unbuffered,
                    ),
                )
        else:
            setattr(sys, self._stream, os.fdopen(self._old_fd, "w"))
            if unbuffered:
                setattr(sys, self._stream, Unbuffered(getattr(sys, self._stream)))

    def install(self):
        if self._installed:
            return

        if os.name == "nt" and sys.version_info >= (3, 6):
            legacy_env_var = "PYTHONLEGACYWINDOWSSTDIO"
            if legacy_env_var not in os.environ:
                msg = (
                    "Set %s environment variable to enable"
                    " console logging on Windows." % legacy_env_var
                )
                logger.error(msg)
                raise Exception(msg)

        logger.info("install start")

        fp = getattr(sys, "__%s__" % self._stream)
        fd = fp.fileno()
        old_fp = os.fdopen(os.dup(fd), "w")

        if self._tee:
            self._dest._set_tee(old_fp.fileno())
        self._dest._start()
        self._installed = True

        self._old_fd = fd
        self._old_fp = old_fp

        self._redirect(to_fd=self._dest._get_writer(), unbuffered=self._unbuffered)
        logger.info("install stop")

    def uninstall(self):
        if self._installed:
            logger.info("uninstall start")
            self._redirect(to_fd=self._old_fp.fileno(), close=True)
            self._dest._stop()
            self._installed = False
            logger.info("uninstall done")


class Capture(object):
    def __init__(self, name, cb, output_writer):
        self._started = False
        self._name = name
        self._cb = cb
        self._output_writer = output_writer
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
        # NB: daemon thread is used because we use atexit to determine when a user
        #     process is finished.  the atexit handler is responsible for flushing,
        #     joining, and closing
        read_thread = threading.Thread(
            name=self._name,
            target=_pipe_relay,
            args=(
                self._stopped,
                self._pipe_rd,
                self._name,
                self._cb,
                self._tee,
                self._output_writer,
            ),
        )
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
        # TODO: need to shut this down cleanly since it is a daemon thread
        self._thread.join(timeout=30)
        if self._thread.is_alive():
            logger.error("Thread did not join: %s", self._name)
            # TODO(jhr): do something better
        logger.info("_stop joined: %s", name)
        os.close(self._pipe_rd)
        logger.info("_stop rd closed: %s", name)
