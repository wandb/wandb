#!/usr/bin/env python

from __future__ import print_function

"""Utilities for capturing output from the current process and processes it
starts.

This file is also a test harness for I/O wrapping: run it as a script with a
shell command in the commandline arguments to see how PTY redirection behaves
for that command.

Watch out for bugs in this module. Uncaught exceptions here may prevent their
own tracebacks from being written to the terminal. Disable STDERR wrapping by
setting WANDB_DEBUG to 'true'.

== Resources

The TTY demystified. Great article on Linux terminals, sessions and process groups.
http://www.linusakesson.net/programming/tty/

Pymux, a Python implementation of tmux:
https://github.com/jonathanslenders/pymux

PTY module source code:
https://github.com/python/cpython/blob/master/Lib/pty.py

PTYProcess from Pexpect, a Python implementation of expect (good *nix support):
https://github.com/pexpect/ptyprocess/blob/master/ptyprocess/ptyprocess.py

https://stackoverflow.com/questions/4675728/redirect-stdout-to-a-file-in-python/22434262#22434262
https://eli.thegreenplace.net/2015/redirecting-all-kinds-of-stdout-in-python/
https://stackoverflow.com/questions/34186035/can-you-fool-isatty-and-log-stdout-and-stderr-separately?rq=1
"""

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

import six
from six.moves import queue, shlex_quote
import wandb.env

logger = logging.getLogger(__name__)

SIGWINCH_HANDLER = None


class SimpleTee(object):
    """Monkey patches the given io to write to itself and the object passed in"""

    def __init__(self, source_io, destination_io):
        self.source_write = source_io.write
        self.destination = destination_io
        source_io.orig_write = self.source_write
        source_io.write = self.write

    def write(self, data):
        self.source_write(data)
        try:
            # We need bytes, but sometimes we get strings
            data = data.encode('utf-8')
        except AttributeError:
            pass
        self.destination.write(data)


class WindowSizeChangeHandler(object):
    """A SIGWINCH handler that keeps a list of FDs to update any time the
    window size changes.

    This is a singleton initialized by init_sigwinch_handler().
    """

    def __init__(self):
        self.fds = []
        # bind one of these so we can compare instances to each other
        self._handler = self._handle_function

    def register(self):
        try:
            old_handler = signal.signal(signal.SIGWINCH, self._handler)
        except ValueError:  # windows
            logger.warn('Setting SIGWINCH handler failed')
        else:
            if old_handler is not None:
                logger.warn('SIGWINCH handler was not None: %r', old_handler)

    def unregister(self):
        try:
            old_handler = signal.signal(signal.SIGWINCH, None)
        except ValueError:  # windows
            logger.warn('Setting SIGWINCH handler failed')
        else:
            if old_handler is not self._handler:
                logger.warn(
                    'SIGWINCH handler was not from W&B: %r', old_handler)

    def add_fd(self, fd):
        self.fds.append(fd)
        self._set_win_sizes()

    def _handle_function(self, signum, frame):
        try:
            self._set_win_sizes()
        except:
            logger.exception('Exception during SIGWINCH')

    def _set_win_sizes(self):
        try:
            win_size = fcntl.ioctl(sys.stdout.fileno(),
                                   termios.TIOCGWINSZ, '\0' * 8)
        except OSError:  # eg. in MPI we can't do this
            rows, cols, xpix, ypix = 25, 80, 0, 0
        else:
            rows, cols, xpix, ypix = struct.unpack('HHHH', win_size)

        if cols == 0:
            cols = 80

        win_size = struct.pack("HHHH", rows, cols, xpix, ypix)

        for fd in self.fds:
            try:
                fcntl.ioctl(fd, termios.TIOCSWINSZ, win_size)
            except OSError:  # eg. in MPI we can't do this
                pass


def init_sigwinch_handler():
    global SIGWINCH_HANDLER
    if SIGWINCH_HANDLER is None and sys.stdout.isatty() and platform.system() != "Windows" and not wandb.env.is_debug():
        SIGWINCH_HANDLER = WindowSizeChangeHandler()
        SIGWINCH_HANDLER.register()


def wandb_pty(resize=True):
    """Get a PTY set to raw mode and registered to hear about window size changes.
    """
    master_fd, slave_fd = pty.openpty()
    # raw mode so carriage returns etc. don't get added by the terminal driver,
    # bash for windows blows up on this so we catch the error and do nothing
    # TODO(adrian): (when) will this be called on windows?
    try:
        tty.setraw(master_fd)
    except termios.error:
        pass

    if resize:
        if SIGWINCH_HANDLER is not None:
            SIGWINCH_HANDLER.add_fd(master_fd)

    return master_fd, slave_fd


class Tee(object):
    """Reads raw data from a file and writes it to other files.

    Writes synchronously to one file and asynchronously to any number of others.
    """

    @classmethod
    def pty(cls, sync_dst_file, *async_dst_files):
        master_fd, slave_fd = wandb_pty()
        master = os.fdopen(master_fd, 'rb')
        tee = cls(master, sync_dst_file, *async_dst_files)
        tee.tee_file = os.fdopen(slave_fd, 'wb')

        return tee

    @classmethod
    def pipe(cls, sync_dst_file, *async_dst_files):
        read_fd, write_fd = os.pipe()
        read_file = os.fdopen(read_fd, 'rb')
        tee = cls(read_file, sync_dst_file, *async_dst_files)
        tee.tee_file = os.fdopen(write_fd, 'wb')

        return tee

    def __init__(self, src_file, sync_dst_file, *async_dst_files):
        """Constructor.

        Args:
            src_file: file to read from.
            sync_dst_file: file to write to synchronously when `self.write()` is
                called.
            async_dst_files: files to write to asynchronously
        """
        # save the stack at construction time for debugging later
        self._origin_stack = '\n'.join(traceback.format_stack())
        self.tee_file = None  # convenience for users that want a writable file to put things into the tee
        self._src_file = src_file
        self._sync_dst_file = sync_dst_file
        self._async_dst_files = list(async_dst_files)
        self._write_queues = []
        self._write_threads = []
        for f in async_dst_files:
            q = queue.Queue()

            t = spawn_reader_writer(q.get, functools.partial(self._write, f))
            self._write_queues.append(q)
            self._write_threads.append(t)

        src_fd = self._src_file.fileno()

        def read():
            # We use `os.read()` instead of `file.read()` because `os.read()` will return
            # any non-empty amount of data, blocking only until there is data available to
            # be read. On the other hand, `file.read()` waits until its buffer is full.
            # Since we use this code for console output, `file.read()`'s stuttering output
            # is undesirable.
            try:
                return os.read(src_fd, 1024)
            except OSError:
                # errno 5 on linux; happens with PTYs if the slave is closed. mac os just
                # returns b'' from os.read().
                return six.b('')

        self._read_thread = spawn_reader_writer(read, self._write_to_all)

    def _write_to_all(self, data):
        self._write(self._sync_dst_file, data)

        for q in self._write_queues:
            q.put(data)

    @classmethod
    def _write(_, f, data):
        if not data:
            # windows explodes if you try to write an empty string to a terminal:
            # OSError: [WinError 87] The parameter is incorrect
            # https://github.com/pytest-dev/py/issues/103
            return
        i = f.write(data)
        if i is not None:  # python 3 w/ unbuffered i/o: we need to keep writing
            while i < len(data):
                i += f.write(data[i:])

    def close_join(self):
        # TODO(adrian): any way we can clean up the read thread properly? do we need to?
        # this hangs in headless mode with python 2. maybe normal behaviour for fdopen on stdout?
        #self._src_file.close()
        #self._read_thread.join()

        self._write_to_all(six.b(''))  # empty bytes is the signal to stop
        for t in self._write_threads:
            t.join()


def spawn_reader_writer(get_data_fn, put_data_fn):
    """Spawn a thread that reads from a data source and writes to a sink.

    The thread will terminate if it receives a Falsey value from the source.

    Args:
        get_data_fn: Data-reading function. Called repeatedly until it returns
            False-y to indicate that the thread should terminate.
        put_data_fn: Data-writing function.
    Returns: threading.Thread
    """
    def _reader_thread():
        while True:
            out = get_data_fn()
            put_data_fn(out)
            if not out:
                # EOF.
                # We've passed this on so things farther down the pipeline will
                # know to shut down.
                break

    t = threading.Thread(target=_reader_thread)
    t.daemon = True
    t.start()
    return t


class WindowsRedirector(object):
    """Simple windows Tee
    """

    def __init__(self, from_stream, to_file):
        self.from_stream = from_stream
        self.to_file = to_file

    def redirect(self):
        self.tee = SimpleTee(self.from_stream, self.to_file)

    def restore(self):
        if not self.to_file.closed:
            self.to_file.close()
        if hasattr(self.from_stream, "orig_write"):
            self.from_stream.write = self.from_stream.orig_write


class FileRedirector(object):
    """Redirects a file object to a different file descriptor.

    Properties:
        redir_file: The file object that gets redirected.
        orig_file: A unbuffered new file object that points where `redir_file` originally pointed.

    Adapted from
    https://stackoverflow.com/questions/4675728/redirect-stdout-to-a-file-in-python/22434262#22434262
    """

    def __init__(self, redir_file, to_file):
        """Constructor

        Args:
            redir_file: (file) The file object to redirect
            to_file: (file) The file object `redir_file` should be redirected to.
        """
        self.redir_file = redir_file
        self._from_fd = redir_file.fileno()
        self._to_fd = to_file.fileno()
        # copy from_fd before it is overwritten
        # NOTE: `self._from_fd` is inheritable on Windows when duplicating a standard stream
        # we make this unbuffered because we want to rely on buffers earlier in the I/O chain
        self.orig_file = os.fdopen(os.dup(self._from_fd), 'wb', 0)

    def redirect(self):
        self.redir_file.flush()  # flush library buffers that dup2 knows nothing about
        # TODO: mirror stdout / err here
        os.dup2(self._to_fd, self._from_fd)  # $ exec >&to

    # This isn't tested properly:
    def restore(self):
        """Restore `self.redir_file` to its original state.
        """
        # NOTE: dup2 makes `self._from_fd` inheritable unconditionally
        self.redir_file.flush()
        os.dup2(self.orig_file.fileno(), self._from_fd)  # $ exec >&copied
        # self.orig_file.close()
        #self.orig_file = None
        #self.redir_file = None
