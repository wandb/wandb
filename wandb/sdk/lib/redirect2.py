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


class TerminalEmulator(object):
    def __init__(self):
        self._screen = pyte.Screen(1000, 100)
        self._stream = pyte.Stream(self._screen)
        self.reset()

    def write(self, text):
        self._stream.feed(text)

    def reset(self):
        self._screen.reset()
        self._last_line_id = None
        self._last_line = None

    def pop_diff(self):
        lines = self._screen.display
        if self._last_line is None:
            if not self._screen.dirty:
                return ''
            self._last_line_id = max(self._screen.dirty)
            self._last_line = lines[self._last_line_id]
            self._screen.dirty.clear()
            return os.linesep.join(lines[:self._last_line_id])
        if self._screen.dirty:
            if self._last_line_id in self._screen.dirty:
                ret = '\r' + os.linesep.join(lines[self._last_line_id - 1: max(self._screen.dirty) + 1])
            else:
                ret = os.linesep.join(lines[self._last_line_id: max(self._screen.dirty) + 1])
            self._last_line_id = max(self._screen.dirty)
            self._last_line = lines[self._last_line_id]
            self._screen.dirty.clear()
        else:
            ret = ''

        return ret
        if len(lines) >= self._num_lines:
            curr_last_line = lines[self._num_lines - 1]
            if curr_last_line != self._last_line:
                ret = '\r' + os.linesep.join(lines[self._num_lines - 1:])
            else:
                ret = os.linesep.join(lines[self._num_lines:])
        else:
            # TODO(frz): how to diff in this state?
            ret = ''
        self._num_lines = len(lines)
        self._last_line = lines[-1]
        return ret
        

class _TerminalEmulator(object):

    ANSI_CSI_RE = re.compile('\001?\033\\[((?:\\d|;)*)([a-zA-Z])\002?')   # Control Sequence Introducer
    ANSI_OSC_RE = re.compile('\001?\033\\]([^\a]*)(\a)\002?')             # Operating System Command

    def __init__(self, mem=50):
        self._history = []
        self._mem = mem
        self.reset()

    def reset(self):
        self.text = ''
        self.cursor = [0, 0]

        # cache
        self._changed = False
        self._lines = ['']

        # to compute diff
        self._num_lines = None
        # TODO(frz): last n lines?
        self._last_line = None


    @property
    def lines(self):
        return re.split('\n|\r\n', self.text)
        if self._changed:
            self._changed = False
            self._lines = re.split('\n|\r\n', self.text)
        return self._lines

    def pop_diff(self):
        lines = self.lines
        if self._num_lines is None:
            self._num_lines = len(lines)
            self._last_line = lines[-1]
            return self.text
        curr_last_line = lines[self._num_lines - 1]
        if curr_last_line != self._last_line:
            ret = '\r' + os.linesep.join(lines[self._num_lines - 1:])
        else:
            ret = os.linesep.join(lines[self._num_lines:])
        self._last_line = lines[-1]
        self._num_lines = len(lines)
        # if self._num_lines > self._mem and self.cursor[0] == self._num_lines - 1:
        #     self._lines = lines[-self._mem:]
        #     self.text = os.linesep.join(self._lines)
        #     self._num_lines = self._mem
        #     self.cursor[0] = self._num_lines - 1
        return ret

    def _get_1d_cursor(self):
        lines_above = self.lines[:self.cursor[1]]
        num_chars_above = sum(map(len, lines_above)) + len(lines_above)
        return num_chars_above + self.cursor[0]

    def _write_plain_text(self, text):
        cursor = self._get_1d_cursor()
        self.text = self.text[:cursor] + text + self.text[cursor + len(text):]
        lines = re.split('\n|\r\n', text)
        n = len(lines) - 1
        self.cursor[0] += n
        if n:
            self.cursor[1] = len(lines[-1])
        else:
            self.cursor[1] += len(text)
        self._changed = True

    def write(self, text):
        self._history.append("write: " + text)
        text = text.replace('\x08', '\033[D')
        text = text.replace('\x07', '')
        for match in self.ANSI_OSC_RE.finditer(text): 
            start, end = match.span()
            text = text[:start] + text[end:]
        prev_end = 0
        for match in self.ANSI_CSI_RE.finditer(text):
            self._history.append("Found match:")
            start, end = match.span()
            self._history.append("Writing plain text: " + text[prev_end: start])
            self._write_plain_text(text[prev_end: start])
            self._history.append("ansi: " + str(match.groups()))
            self._process_ansi(*match.groups())
            prev_end = end
        self._write_plain_text(text[prev_end:])

    def _process_ansi(self, paramstring, command):
        self._history.append((paramstring, command))
        # https://en.wikipedia.org/wiki/ANSI_escape_code
        if command in 'Hf':
            params = tuple(int(p) if len(p) != 0 else 1 for p in paramstring.split(';'))
            while len(params) < 2:
                params = params + (1,)
        else:
            params = tuple(int(p) for p in paramstring.split(';') if len(p) != 0)
            if len(params) == 0:
                if command in 'JKm':
                    params = (0,)
                elif command in 'ABCD':
                    params = (1,)
        lines = self.lines
        if command == 'm':
            # TODO(frz)
            pass
        elif command == 'J':
            n = params[0]
            if n == 0:
                self.text = self.text[:self._get_1d_cursor()]
            elif n == 1:
                self.text = self.text[self._get_1d_cursor():]
                self.cursor = [0, 0]
            elif n >= 2:
                self.text = ''
                self.cursor = [0, 0]
        elif command == 'K':
            n = params[0]
            if n == 0:
                cy, cx = self.cursor
                curr_line = lines[cy]
                self.text = os.linesep.join(lines[:cy] + [curr_line[:cx] + ' ' * (len(curr_line) - cx)] + lines[cy:])
            elif n == 1:
                cx, cy = self.cursor
                curr_line = lines[cy]
                self.text = os.linesep.join(lines[:cy] + [' ' * cx + curr_line[cx:]] + lines[cy:])
            elif n == 2:
                cy = self.cursor[1]
                curr_line = lines[cy]
                self.text = os.linesep.join(lines[:cy] + [' ' * len(curr_line)] + lines[cy:])
        elif command in 'Hf':
            n, m = params
            # values are 1 based
            n -= 1
            m -= 1
            n = max(0, n)
            m = max(0, m)
            cx, cy = self.cursor
            max_cy = max(0, len(lines) - 1)
            cy = min(n, max_cy)
            max_cx = len(lines[cy])
            cx = min(m, max_cx)
            self.cursor = [cx, cy]
        elif command == 'C':
            n = params[0]
            max_cx = len(lines[self.cursor[0]])
            self.cursor[1] = min(self.cursor[1] + n, max_cx)
        elif command == 'D':
            n = params[0]
            self.cursor[1] = max(0, self.cursor[1] - n)
        elif command == 'A':
            n = params[0]
            max_cy = max(0, len(lines) - 1)
            self.cursor[0] = min(self.cursor[0] + n, max_cy)
        elif command == 'B':
            n = params[0]
            self.cursor[0] = max(0, self.cursor[0] - n)
            
            

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
            data = self._emulator.pop_diff().encode('utf-8')
            for cb in self.cbs:
                try:
                    cb(data)
                except Exception as e:
                    print(e)
