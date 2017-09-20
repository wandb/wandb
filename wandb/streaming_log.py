import datetime
import io
import tempfile
import time
import sys
from requests import Session
from wandb import Api
from six.moves import queue
import threading
import traceback
import logging
import re
import signal
import os
import logging
import six
logger = logging.getLogger(__name__)


class LineBuffer(object):
    """Streaming string parser that extracts lines."""

    def __init__(self):
        self._buf = []
        self._line_end_re = re.compile('[\r\n]')

    def add_string(self, string):
        """Process a string.

        Args:
            string: Any string
        Returns:
            list of found lines, remainder will be buffered.
        """
        lines = []
        while string:
            match = self._line_end_re.search(string)
            if match is None:
                self._buf.append(string)
                break
            else:
                line_end_pos = match.start()
                lines.append(''.join(self._buf) + string[:line_end_pos + 1])
                string = string[line_end_pos + 1:]
                self._buf = []
        return lines


class TextStreamPusher(object):
    """Pushes a stream of text, line by line, to wandb."""

    def __init__(self, fsapi, filename, line_prepend='', prepend_timestamp=False):
        """Conctructor.

        Args:
            fsapi: api.FileStreamApi instance
            filename: Name of the file this stream is pushed to.
            line_prepend: string to prepend to every line for this stream.
            prepend_timestamp: If true a timestamp will be prepended to each line
                (after line_prepend).
        """
        self._fsapi = fsapi
        self._filename = filename
        if line_prepend:
            line_prepend += ' '
        self._line_prepend = line_prepend
        self._prepend_timestamp = prepend_timestamp
        self._line_buffer = LineBuffer()

    def write(self, message, cur_time=None):
        """Write some text to the pusher.

        Args:
            message: a string to push for this file.
            cur_time: used for unit testing. override line timestamp.
        """
        if cur_time is None:
            cur_time = time.time()
        lines = self._line_buffer.add_string(message)
        for line in lines:
            timestamp = ''
            if self._prepend_timestamp:
                timestamp = datetime.datetime.utcfromtimestamp(
                    cur_time).isoformat() + ' '
            line = '%s%s%s' % (self._line_prepend, timestamp, line)
            self._fsapi.push(self._filename, line)

    def close(self):
        """Close the file."""
        # Force a final line to clear whatever might be in the buffer.
        self.write('\n')
