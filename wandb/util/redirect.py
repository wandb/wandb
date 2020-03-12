
import os
import threading
import sys
import logging


logger = logging.getLogger("wandb")


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
    while not stopped.isSet():
        logger.info("relay read")
        try:
            data = os.read(fd, 1000)
        except OSError as e:
            # TODO(jhr): handle this
            logger.info("got read error")
            return
        if len(data) == 0:
            logger.info("got no data")
            break
        if tee:
            logger.info("tee write")
            os.write(tee, data)
        #print("[%s]" % data, file=sys.stderr)
        if cb:
            logger.info("callback")
            cb(name, data)
            logger.info("callback done")
    logger.info("relay done")
    os.close(fd)
    logger.info("relay done done")


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
        fp.close()
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
        self._dest._stop()
        self._redirect(to_fd=self._old_fp.fileno())
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
        read_thread = threading.Thread(name=self._name, target=_pipe_relay, daemon=True, args=(self._stopped, self._pipe_rd, self._name, self._cb, self._tee))
        read_thread.start()
        self._thread = read_thread

    def _stop(self):
        logger.info("_stop")
        self._stopped.set()
        os.close(self._pipe_wr)
        logger.info("_stop closed")
        # FIXME: need to shut this down cleanly since it is a daemon thread
        # self._thread.join()
