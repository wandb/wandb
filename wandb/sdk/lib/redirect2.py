import atexit
import functools
import io
import logging
import os
try:
    import fcntl
    import pty
    import tty
    import termios
except ImportError:  # windows
    pty = tty = termios = fcntl = None

import signal
import struct
import subprocess
import sys
import tempfile
import threading
import traceback
import platform

import re
import six
from six.moves import queue, shlex_quote
import pyte

from .terminal_emulator import TerminalEmulator

_redirects = {}




class BaseRedirect(object):
    def __init__(self, src, cbs=[]):
        assert hasattr(sys, src)
        self.src = src
        self.cbs = cbs

    @property
    def src_stream(self):
        return getattr(sys, "__%s__" % self.src)

    @property
    def src_fd(self):
        return self.src_stream.fileno()

    @property
    def src_wrapped_stream(self):
        return getattr(sys, self.src)

    def install(self):
        raise NotImplementedError


    def uninstall(self):
        raise NotImplementedError


class StreamWrapper(BaseRedirect):
    def __init__(self, src, cbs=[]):
        super(StreamWrapper, self).__init__(src=src, cbs=cbs)
        self._installed = False

    def install(self):
        stream = self.src_wrapped_stream
        self.old_write = stream.write

        def write(data):
            self.old_write(data)
            if not isinstance(data, bytes):
                data = data.encode('utf-8')
            for cb in self.cbs:
                cb(data)
        stream.write = write
        self._installed = True

    def uninstall(self):
        if not self._installed:
            return
        self.src_wrapped_stream.write = self.old_write
        self._installed = False


class Unbuffered(StreamWrapper):
    def __init__(self, src):
        super(Unbuffered, self).__init__(src=src, cbs=[lambda _: getattr(sys, src).flush()])


class Redirect(BaseRedirect):
    def __init__(self, src, cbs=[]):
        super(Redirect, self).__init__(src=src, cbs=cbs)
        self._old_handler = None
        self._installed = False
        self._emulator = TerminalEmulator()

    def _pipe(self):
        if pty:
            m, s = pty.openpty()
            try:
                tty.setraw(m)
            except termios.error:
                pass

            def handle_window_size_change():
                try:
                    win_size = fcntl.ioctl(self.src_fd,
                                        termios.TIOCGWINSZ, '\0' * 8)
                    rows, cols, xpix, ypix = struct.unpack('HHHH', win_size)
                except OSError:  # eg. in MPI we can't do this
                    rows, cols, xpix, ypix = 25, 80, 0, 0
                if cols == 0:
                    cols = 80
                win_size = struct.pack("HHHH", rows, cols, xpix, ypix)
                fcntl.ioctl(m, termios.TIOCSWINSZ, win_size)
            
            old_handler = signal.signal(signal.SIGWINCH, lambda *_: None)
            def handler(signum, frame):
                if callable(old_handler):
                    old_handler(signum, frame)
                handle_window_size_change()
            self._old_handler = old_handler
            signal.signal(signal.SIGWINCH, handler)
            r, w = m, s
        else:
            r, w = os.pipe()
        return r, w

    def install(self):
        if self._installed:
            return
        self._pipe_read_fd, self._pipe_write_fd = self._pipe()
        self._orig_src_fd = os.dup(self.src_fd)
        self._orig_src = os.fdopen(self._orig_src_fd, 'wb', 0)
        os.dup2(self._pipe_write_fd, self.src_fd)
        self._thread = threading.Thread(target=self._pipe_relay, daemon=True)
        self._installed = True
        self._thread.start()

    def uninstall(self):
        if not self._installed:
            return
        self._installed = False
        self._thread.join()
        if self._old_handler:
            signal.signal(signal.SIGWINCH, self._old_handler)
        os.dup2(self._orig_src_fd, self.src_fd)

    def _pipe_relay(self):
        while self._installed:
            try:
                data = os.read(self._pipe_read_fd, 4096)
            except OSError:
                data = six.b('')
            i = self._orig_src.write(data)
            if i is not None:  # python 3 w/ unbuffered i/o: we need to keep writing
                while i < len(data):
                    i += self._orig_src.write(data[i:])
            self._emulator.write(data.decode('utf-8'))
            data = self._emulator.read(1).encode('utf-8')
            if data:
                for cb in self.cbs:
                    try:
                        cb(data)
                    except Exception as e:
                        print(e)
