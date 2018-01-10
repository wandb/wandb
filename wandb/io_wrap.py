#!/usr/bin/env python

"""Utilities for capturing output from the current process and processes it
starts.
"""

import logging
import threading
import sys

from six.moves import queue

logger = logging.getLogger(__name__)


class OutStreamTee(object):
    """Tees a writable filelike object.

    writes/flushes to the passed in stream will go to the stream
    and a second stream.
    """

    def __init__(self, stream, second_stream):
        """Constructor.

        Args:
            stream: stream to tee.
            second_stream: stream to duplicate writes to.
        """
        self._orig_stream = stream
        self._second_stream = second_stream
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True
        self._thread.start()

    def _thread_body(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            self._second_stream.write(item)

    def fileno(self):
        return self._orig_stream.fileno()

    def write(self, message):
        self._orig_stream.write(message)
        self._queue.put(message)

    def flush(self):
        self._orig_stream.flush()

    def isatty(self):
        return self._orig_stream.isatty()

    def close(self):
        self._queue.put(None)


def python_io_wrap(stdout_pusher, stderr_pusher):
    """Simple stdout/stderr wrapping that will capture output only from this
    Python process and its threads.
    """
    sys.stdout = OutStreamTee(sys.stdout, stdout_pusher)
    sys.stderr = OutStreamTee(sys.stderr, stderr_pusher)
