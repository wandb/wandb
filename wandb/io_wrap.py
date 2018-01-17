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
import io
import logging
import os
import pty
import subprocess
import sys
import tempfile
import threading

from six.moves import queue, shlex_quote

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
        i = self._sync_file.write(message)
        if i is not None:  # python 3 w/ unbuffered i/o: we need to keep writing
            while i < len(message):
                i += self._sync_file.write(message[i:])

        for q in self._queues:
            q.put(message)

    # we implement the optional parts of the file interface so these FileTee objects
    # can be used as in case the user's program uses them
    def fileno(self):
        return self._sync_file.fileno()

    def flush(self):
        self._sync_file.flush()

    def close(self):
        self._sync_file.close()
        for q in self._queues:
            q.put(None)

    def isatty(self):
        if hasattr(self._sync_file, 'isatty'):
            return self._sync_file.isatty()
        else:
            return False


def spawn_reader_writer(get_data_fn, put_data_fn):
    """Spawn a thread that reads from a data source and writes to a sink.

    The thread will terminate if it receives None from the source.

    Args:
        get_data_fn: Data-reading function. Called repeatedly until it returns
            None to indicate that the thread should terminate.
        put_data_fn: Data-writing function. Called every time `get_data_fn`
            returns something other than None.
    Returns: threading.Thread
    """
    def _reader_thread():
        while True:
            out = get_data_fn()
            if out is None:
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
    new_stdout = FileTee(sys.stdout, stdout_pusher)
    try:
        new_stdout.encoding = sys.stdout.encoding
    except AttributeError:
        pass
    try:
        new_stdout.errors = sys.stdout.errors
    except AttributeError:
        pass
    sys.stdout = new_stdout
    if os.environ.get('WANDB_DEBUG') != 'true':
        sys.stderr = FileTee(sys.stderr, stderr_pusher)
        try:
            new_stderr.encoding = sys.stderr.encoding
        except AttributeError:
            pass
        try:
            new_stderr.errors = sys.stderr.errors
        except AttributeError:
            pass


class PtyIoWrap(object):
    """Captures STDOUT and STDERR of the current process using PTYs

    OS-level (file descriptor) redirection means child processes' output is
    also captured.

    Using PTYs causes libc to use normal terminal-style buffering instead of
    the large fixed-size buffers it uses when output goes to PIPEs.

    FIXME(adrian): Some processes may not behave properly unless the PTY is
    their controlling terminal.
    """
    def __init__(self, stdout_readers=None, stderr_readers=None):
        if stdout_readers is None:
            stdout_readers = []
        if stderr_readers is None:
            stderr_readers = []

        # TODO(adrian): handle failures in the following:
        stdout_master_fd, stdout_slave_fd = pty.openpty()
        stderr_master_fd, stderr_slave_fd = pty.openpty()

        self._stdout_slave = os.fdopen(stdout_slave_fd, 'wb')
        self._stderr_slave = os.fdopen(stderr_slave_fd, 'wb')

        self._stdout_redirector = FileRedirector(sys.stdout, self._stdout_slave)
        self._stdout_tee = FileTee(self.orig_stdout, *stdout_readers)

        self._stderr_redirector = FileRedirector(sys.stderr, self._stderr_slave)
        self._stderr_tee = FileTee(self.orig_stderr, *stderr_readers)

        # `os.read()` doesn't block until the read buffer is completely full the way
        # `file.read()` does. we use `os.read()` here hoping it will help our eventual
        # output look like it would have without any I/O wrapping.
        self._stdout_reader_writer = spawn_reader_writer(
            lambda: (os.read(stdout_master_fd, 1024) or None),
            self._stdout_tee.write
        )
        self._stderr_reader_writer = spawn_reader_writer(
            lambda: (os.read(stderr_master_fd, 1024) or None),
            self._stderr_tee.write
        )

        self._stdout_redirector.redirect()
        if os.environ.get('WANDB_DEBUG') != 'true':
            self._stderr_redirector.redirect()

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
        orig_file: A unbuffered new file object that points where `redir_file` originally pointed.

    Adapted from
    https://stackoverflow.com/questions/4675728/redirect-stdout-to-a-file-in-python/22434262#22434262
    """
    def __init__(self, redir_file, to_file):
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
        # we make this unbuffered because we want to rely on buffers earlier in the I/O chain
        self.orig_file = os.fdopen(os.dup(self._from_fd), 'wb', 0)

    def redirect(self):
        self.redir_file.flush()  # flush library buffers that dup2 knows nothing about
        os.dup2(self._to_fd, self._from_fd)  # $ exec >&to

    '''
    This isn't tested properly:
    def restore(self):
        """Restore `self.redir_file` to its original state.

        This function may only be called once.
        """
        #NOTE: dup2 makes `self._from_fd` inheritable unconditionally
        self.redir_file.flush()
        os.dup2(self.orig_file.fileno(), self._from_fd)  # $ exec >&copied
        #self.orig_file.close()
        #self.orig_file = None
        self.redir_file = None
    '''


if __name__ == '__main__':
    cmd = ' '.join(shlex_quote(arg) for arg in sys.argv[1:])
    print(cmd)
    wrapper = PtyIoWrap()
    subprocess.call(cmd, shell=True)