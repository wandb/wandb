#!/usr/bin/env python

from __future__ import print_function

import datetime
import logging
import os
import re
import time

from six import b

logger = logging.getLogger(__name__)


class LineBuffer(object):
    """Streaming string parser that extracts lines."""

    def __init__(self):
        self._buf = []
        # If the backend receive a line ending with \r, it assumes that
        # line is part of a progress bar and ignores it. To handle terminal
        # output properly on Windows we need to ensure we always pass along
        # a newline if it comes after a carriage return.
        self._line_end_re = re.compile(b('\r\n|\r|\n'))

    def add_string(self, data):
        """Process some data splitting it into complete lines and buffering the rest

        Args:
            data: A `str` in Python 2 or `bytes` in Python 3
        Returns:
            list of complete lines ending with a carriage return (eg. a progress
            bar) or a newline.
        """
        lines = []
        while data:
            match = self._line_end_re.search(data)
            if match is None:
                chunk = data
            else:
                chunk = data[:match.end()]

            data = data[len(chunk):]

            if self._buf and self._buf[-1].endswith(b('\r')) and not chunk.startswith(b('\n')):
                # if we get a carriage return followed by something other than
                # a newline then we assume that we're overwriting the current
                # line (ie. a progress bar)
                #
                # We don't terminate lines that end with a carriage return until
                # we see what's coming next so we can distinguish between a
                # progress bar situation and a Windows line terminator.
                #
                # TODO(adrian): some day these hacks should be replaced with
                # real terminal emulation
                lines.append(self._finish_line())

            self._buf.append(chunk)
            if chunk.endswith(b('\n')):
                lines.append(self._finish_line())

        return lines

    def _finish_line(self):
        line = b('').join(self._buf).decode('utf-8')
        self._buf = []
        return line


class TextStreamPusher(object):
    """Pushes a stream of text, line by line, to wandb."""

    def __init__(self, fsapi, filename, line_prepend='', prepend_timestamp=False):
        """Constructor.

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

    def write_string(self, message, cur_time=None):
        return self.write(message.encode('utf-8'), cur_time)

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
            #print('ts line', repr(line))
            timestamp = ''
            if self._prepend_timestamp:
                timestamp = datetime.datetime.utcfromtimestamp(
                    cur_time).isoformat() + ' '
            line = '%s%s%s' % (self._line_prepend, timestamp, line)
            self._fsapi.push(self._filename, line)

    def close(self):
        """Close the file."""
        # Force a final line to clear whatever might be in the buffer.
        self.write_string(os.linesep)
