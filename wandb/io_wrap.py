#!/usr/bin/env python

"""Utilities for capturing output from the current process and processes it
starts.

This file is also a test harness for I/O wrapping: run it as a script with a
shell command in the commandline arguments to see how PTY redirection behaves
for that command.

== Resources

The TTY demystified. Great article on Linux terminals, sessions and process groups.
http://www.linusakesson.net/programming/tty/

Pymux, a Python implementation of tmux:
https://github.com/jonathanslenders/pymux

PTY module source code:
https://github.com/python/cpython/blob/master/Lib/pty.py

PTYProcess from Pexpect, a Python implementation of expect (good *nix support):
https://github.com/pexpect/ptyprocess/blob/master/ptyprocess/ptyprocess.py

https://eli.thegreenplace.net/2015/redirecting-all-kinds-of-stdout-in-python/
https://stackoverflow.com/questions/4675728/redirect-stdout-to-a-file-in-python/22434262#22434262
https://stackoverflow.com/questions/34186035/can-you-fool-isatty-and-log-stdout-and-stderr-separately?rq=1
"""

import ctypes
import io
import logging
import os
import pty
import sys
import tempfile
import threading

from six.moves import queue

logger = logging.getLogger(__name__)


class FileTee(object):
    """Tees a writable filelike object.

    Writes synchronously to one file and asynchronously to any number of others.
    """

    def __init__(self, sync_file, *async_files):
        """Constructor.

        Args:
            sync_file: file to write to synchronously when `self.write()` is
                called.
            async_files: files to write to asynchronously
        """
        self._sync_file = sync_file
        self._async_files = list(async_files)
        self._queues = []
        self._threads = []
        for f in async_files:
            q = queue.Queue()
            self._queues.append(q)
            self._threads.append(spawn_reader_writer(q.get, f.write))

    def write(self, message):
        self._sync_file.write(message)
        for q in self._queues:
            q.put(message)

    # we implement the optional parts of the file interface in case the user's program uses them
    def fileno(self):
        return self._orig_stream.fileno()

    def flush(self):
        self._orig_stream.flush()

    def close(self):
        self._queue.put(None)


def spawn_reader_writer(get_data_fn, put_data_fn):
    def _reader_thread():
        while True:
            out = get_data_fn()
            if not out:
                break
            put_data_fn(out)

    t = threading.Thread(target=_reader_thread)
    t.daemon = True
    t.start()
    return t


def python_io_wrap(stdout_pusher, stderr_pusher):
    """Simple stdout/stderr wrapping that will capture output only from this
    Python process and its threads. Won't work for non-Python processes or any
    libraries that do lower-level I/O directly.
    """
    sys.stdout = FileTee(sys.stdout, stdout_pusher)
    sys.stderr = FileTee(sys.stderr, stderr_pusher)


class PtyIoWrap(object):
    """OS-level I/O wrapping using PTYs

    Using PTYs causes libc to use normal terminal-style buffering instead of
    the large fixed-size buffers it uses when output goes to PIPEs.
    """
    def __init__(self, stdout_readers=None, stderr_readers=None):
        if stdout_readers is None:
            stdout_readers = []
        if stderr_readers is None:
            stderr_readers = []

        stdout_master_fd, stdout_slave_fd = pty.openpty()
        stderr_master_fd, stderr_slave_fd = pty.openpty()

        self._stdout_master = os.fdopen(stdout_master_fd, 'rwb')
        self._stdout_slave = os.fdopen(stdout_slave_fd, 'rwb')
        self._stderr_master = os.fdopen(stderr_master_fd, 'rwb')
        self._stderr_slave = os.fdopen(stderr_slave_fd, 'rwb')

        # TODO(adrian): should probably set orig_stdout to unbuffered because we
        # want the new stdout to take care of any buffering
        self._stdout_redirector = FileRedirector(sys.stdout, self._stdout_slave)
        self._stdout_tee = FileTee(self.orig_stdout, *stdout_readers)
        # TODO(adrian): reading chunks like this causes stuttered output. is
        # there a better solution than always reading one byte (or one line) at
        # a time? looks like os.read() might be a good solution.
        self._stdout_reader_writer = spawn_reader_writer(
            lambda: self._stdout_master.read(64),
            self._stdout_tee.write
        )

        self._stderr_redirector = FileRedirector(sys.stderr, self._stderr_slave)
        self._stderr_tee = FileTee(self.orig_stderr, *stderr_readers)
        self._stderr_reader_writer = spawn_reader_writer(
            lambda: self._stderr_master.read(64),
            self._stderr_tee.write
        )

    @property
    def orig_stdout(self):
        return self._stdout_redirector.orig_file

    @property
    def orig_stderr(self):
        return self._stderr_redirector.orig_file


class FileRedirector(object):
    """Redirects a file object to a different file descriptor.

    Properties:
        redir_file: The file object that gets redirected.
        orig_file: A new file object that points where `redir_file` originally pointed.

    Adapted from
    https://stackoverflow.com/questions/4675728/redirect-stdout-to-a-file-in-python/22434262#22434262
    """
    def __init__(self, redir_file, to_file): #to=os.devnull, stdout=None):
        """Constructor

        Args:
            redir_file: (file) The file object to redirect
            to_file: (file) The file descriptor `redir_file` should be redirected to.
        """
        self.redir_file = redir_file
        self._from_fd = redir_file.fileno()
        self._to_fd = to_file.fileno()
        # copy from_fd before it is overwritten
        #NOTE: `self._from_fd` is inheritable on Windows when duplicating a standard stream
        self.orig_file = os.fdopen(os.dup(self._from_fd), 'wb')

        self._redirect()

    def _redirect(self):
        self.redir_file.flush()  # flush library buffers that dup2 knows nothing about
        os.dup2(self._to_fd, self._from_fd)  # $ exec >&to

    def restore(self):
        """Restore `self.redir_file` to its original state.

        This function may only be called once.
        """
        #NOTE: dup2 makes `self._from_fd` inheritable unconditionally
        self.redir_file.flush()
        os.dup2(self.orig_file.fileno(), self._from_fd)  # $ exec >&copied
        self.orig_file.close()
        self.orig_file = None
        self.redir_file = None


if __name__ == '__main__':
    wrapper = PtyIoWrap()
    import subprocess
    subprocess.call(sys.argv[1:], shell=True)
