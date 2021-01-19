try:
    import fcntl
    import pty
    import tty
    import termios
except ImportError:  # windows
    pty = tty = termios = fcntl = None  # type: ignore

import itertools
import logging
import os
import signal
import struct
import sys
import threading
import time

import pyte  # type: ignore
from pyte.control import CSI  # type: ignore
from pyte.escape import SGR  # type: ignore
import wandb

logger = logging.getLogger("wandb")

_redirects = {"stdout": None, "stderr": None}


# Reverse graphic maps
FG = {
    v: str(k)
    for k, v in itertools.chain(
        pyte.graphics.FG.items(), pyte.graphics.FG_AIXTERM.items()
    )
}
BG = {
    v: str(k)
    for k, v in itertools.chain(
        pyte.graphics.BG.items(), pyte.graphics.BG_AIXTERM.items()
    )
}
FG_256 = str(pyte.graphics.FG_256)  # 38
BG_256 = str(pyte.graphics.BG_256)  # 48
FG_BG_256 = {x: str(i) for (i, x) in enumerate(pyte.graphics.FG_BG_256)}
TEXT = {v: str(k) for k, v in pyte.graphics.TEXT.items()}
BIT_256 = ";5;"
BIT_24 = ";2;"


def _hex_string_to_int_string(h):
    return ";".join(str(int(h[i : i + 2], 16)) for i in range(0, len(h), 2))


class InfiniteScreen(pyte.Screen):
    def __init__(self):
        super(InfiniteScreen, self).__init__(columns=5, lines=5)
        self._prev_num_lines = None
        self._prev_last_line = None
        self.set_mode(pyte.modes.LNM)

    def reset(self):
        super(InfiniteScreen, self).reset()
        self._prev_num_lines = None
        self._prev_last_line = None

    @property
    def _lines(self):
        for i in range(self.lines - 1, -1, -1):
            if i in self.buffer and self._len(i):
                return i + 1
        return 1

    def _len(self, line):
        line = self.buffer[line]
        for i in range(self.columns - 1, -1, -1):
            if line[i] != self.default_char:
                return i + 1
        return 0

    @property
    def display(self):
        return [
            "".join(self.buffer[i][j].data for j in range(self._len(i)))
            for i in range(self._lines)
        ]

    def _get_line(self, line, formatting=True):
        if not formatting:
            return "".join([self.buffer[line][i].data for i in range(self._len(line))])
        ret = ""
        prev_char = self.default_char
        for i in range(self._len(line)):
            c = self.buffer[line][i]
            if c.fg != prev_char.fg:
                fg_code = FG.get(c.fg)
                if fg_code:
                    ret += CSI + fg_code + SGR
                else:
                    fg_code = FG_BG_256.get(c.fg)
                    if fg_code:
                        ret += CSI + FG_256 + BIT_256 + fg_code + SGR
                    else:
                        ret += (
                            CSI
                            + FG_256
                            + BIT_24
                            + _hex_string_to_int_string(c.fg)
                            + SGR
                        )
            if c.bg != prev_char.bg:
                bg_code = BG.get(c.bg)
                if bg_code:
                    ret += CSI + bg_code + SGR
                else:
                    bg_code = FG_BG_256.get(c.bg)
                    if bg_code:
                        ret += CSI + BG_256 + BIT_256 + bg_code + SGR
                    else:
                        ret += (
                            CSI
                            + BG_256
                            + BIT_24
                            + _hex_string_to_int_string(c.bg)
                            + SGR
                        )
            for i, attr in list(enumerate(c._fields))[3:]:  # skip data, fg, bg
                if c[i] != prev_char[i]:
                    ret += CSI + TEXT[("-", "+")[c[i]] + attr] + SGR
            ret += c.data
            prev_char = c
        return ret

    def index(self):
        if self.cursor.y == self.lines - 1:
            self.lines += 1
        self.cursor_down()

    def draw(self, data):
        columns_remaining = self.columns - self.cursor.x
        if columns_remaining < len(data):
            self.columns += len(data) - columns_remaining
        super(InfiniteScreen, self).draw(data)

    def insert_characters(self, count=None):
        count = count or 1
        n = self._len(self.cursor.y)
        if self.cursor.x >= n:
            columns_remaining = self.columns - self.cursor.x
        else:
            columns_remaining = self.columns - n
        if columns_remaining < count:
            self.columns += count - columns_remaining
        super(InfiniteScreen, self).insert_characters(count=count)

    def insert_lines(self, count=None):
        count = count or 1
        lines_remaining = self.lines - self._lines
        if lines_remaining < count:
            self.lines += count - lines_remaining
        super(InfiniteScreen, self).insert_lines(count=count)

    def pop_diff(self):
        num_lines = self._lines
        if self._prev_num_lines is None:
            ret = os.linesep.join(map(self._get_line, range(num_lines)))
            if ret:
                ret += os.linesep
            else:
                return ret
        else:
            curr_line = self._get_line(self._prev_num_lines - 1)
            if curr_line == self._prev_last_line:
                if num_lines == self._prev_num_lines:
                    return ""
                ret = (
                    os.linesep.join(
                        map(self._get_line, range(self._prev_num_lines, num_lines))
                    )
                    + os.linesep
                )
            else:
                ret = (
                    "\r"
                    + os.linesep.join(
                        map(self._get_line, range(self._prev_num_lines - 1, num_lines))
                    )
                    + os.linesep
                )
        self._prev_num_lines = num_lines
        self._prev_last_line = self._get_line(num_lines - 1)
        return ret


class TerminalEmulator(object):
    def __init__(self):
        self._screen = InfiniteScreen()
        self._stream = pyte.Stream(self._screen)

    def write(self, data):
        self._stream.feed(data)

    def read(self, min_lines=0):
        screen = self._screen
        if min_lines:
            new_lines = screen._lines
            if screen._prev_num_lines:
                new_lines -= screen._prev_num_lines
            if new_lines < min_lines:
                return ""
        return screen.pop_diff()

    def reset(self):
        self._screen.reset()


_MIN_CALLBACK_INTERVAL = 2  # seconds


class RedirectBase(object):
    def __init__(self, src, cbs=()):
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
        curr_redirect = _redirects.get(self.src)
        if curr_redirect and curr_redirect != self:
            curr_redirect.uninstall()
        _redirects[self.src] = self

    def uninstall(self):
        if _redirects[self.src] != self:
            return
        _redirects[self.src] = None


class _WrappedStream(object):
    """
    For python 2.7 only.
    """

    def __init__(self, stream, write_f):
        object.__setattr__(self, "write", write_f)
        object.__setattr__(self, "_stream", stream)

    def __getattr__(self, attr):
        return getattr(self._stream, attr)


class StreamWrapper(RedirectBase):
    def __init__(self, src, cbs=()):
        super(StreamWrapper, self).__init__(src=src, cbs=cbs)
        self._installed = False
        self._emulator = TerminalEmulator()

    def install(self):
        super(StreamWrapper, self).install()
        if self._installed:
            return
        stream = self.src_wrapped_stream
        old_write = stream.write
        self._prev_callback_timestamp = time.time()
        self._old_write = old_write

        def write(data):
            self._old_write(data)
            if isinstance(data, bytes):
                try:
                    data = data.decode("utf-8")
                except UnicodeDecodeError:
                    # TODO(frz)
                    data = ""
            self._emulator.write(data)
            curr_time = time.time()
            if curr_time - self._prev_callback_timestamp < _MIN_CALLBACK_INTERVAL:
                return
            data = self._emulator.read().encode("utf-8")
            if data:
                self._prev_callback_timestamp = curr_time
                for cb in self.cbs:
                    try:
                        cb(data)
                    except Exception:
                        pass  # TODO(frz)

        if sys.version_info[0] > 2:
            stream.write = write
        else:
            self._old_stream = stream
            setattr(sys, self.src, _WrappedStream(stream, write))
        self._installed = True

    def flush(self):
        data = self._emulator.read().encode("utf-8")
        if data:
            for cb in self.cbs:
                try:
                    cb(data)
                except Exception:
                    pass  # TODO(frz)

    def uninstall(self):
        if not self._installed:
            return
        self.flush()
        if sys.version_info[0] > 2:
            self.src_wrapped_stream.write = self._old_write
        else:
            setattr(sys, self.src, self._old_stream)
        self._installed = False
        super(StreamWrapper, self).uninstall()


class _WindowSizeChangeHandler(object):
    def __init__(self):
        self._fds = set()

    def _register(self):
        old_handler = signal.signal(signal.SIGWINCH, lambda *_: None)

        def handler(signum, frame):
            if callable(old_handler):
                old_handler(signum, frame)
            self.handle_window_size_change()

        signal.signal(signal.SIGWINCH, handler)
        self._old_handler = old_handler

    def _unregister(self):
        signal.signal(signal.SIGWINCH, self._old_handler)

    def add_fd(self, fd):
        if not self._fds:
            self._register()
        self._fds.add(fd)
        self.handle_window_size_change()

    def remove_fd(self, fd):
        if fd in self._fds:
            self._fds.remove(fd)
            if not self._fds:
                self._unregister()

    def handle_window_size_change(self):
        try:
            win_size = fcntl.ioctl(0, termios.TIOCGWINSZ, "\0" * 8)
            rows, cols, xpix, ypix = struct.unpack("HHHH", win_size)
        # Note: IOError not subclass of OSError in python 2.x
        except (OSError, IOError):  # eg. in MPI we can't do this. # noqa
            rows, cols, xpix, ypix = 25, 80, 0, 0
        if cols == 0:
            cols = 80
        win_size = struct.pack("HHHH", rows, cols, xpix, ypix)
        for fd in self._fds:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, win_size)


_WSCH = _WindowSizeChangeHandler()


class Redirect(RedirectBase):
    def __init__(self, src, cbs=()):
        super(Redirect, self).__init__(src=src, cbs=cbs)
        self._installed = False
        self._emulator = TerminalEmulator()

    def _pipe(self):
        if pty:
            r, w = pty.openpty()
        else:
            r, w = os.pipe()
        return r, w

    def install(self):
        super(Redirect, self).install()
        if self._installed:
            return
        self._pipe_read_fd, self._pipe_write_fd = self._pipe()
        if os.isatty(self._pipe_read_fd):
            _WSCH.add_fd(self._pipe_read_fd)
        self._orig_src_fd = os.dup(self.src_fd)
        self._orig_src = os.fdopen(self._orig_src_fd, "wb", 0)
        os.dup2(self._pipe_write_fd, self.src_fd)
        self._installed = True
        self._stopped = threading.Event()
        # self._prev_callback_timestamp = time.time()
        self._pipe_relay_thread = threading.Thread(target=self._pipe_relay)
        self._pipe_relay_thread.daemon = True
        self._pipe_relay_thread.start()
        if not wandb.run or wandb.run._settings.mode == "online":
            self._callback_thread = threading.Thread(target=self._callback)
            self._callback_thread.daemon = True
            self._callback_thread.start()

    def uninstall(self):
        if not self._installed:
            return
        self._installed = False
        self.src_wrapped_stream.flush()
        time.sleep(1)
        self._stopped.set()
        os.dup2(self._orig_src_fd, self.src_fd)
        os.write(self._pipe_write_fd, b"\n")
        os.close(self._pipe_write_fd)
        os.close(self._pipe_read_fd)
        self.flush()
        _WSCH.remove_fd(self._pipe_read_fd)
        super(Redirect, self).uninstall()

    def flush(self):
        data = self._emulator.read().encode("utf-8")
        if data:
            for cb in self.cbs:
                try:
                    cb(data)
                except Exception:
                    pass  # TODO(frz)

    def _callback(self):
        while not self._stopped.is_set():
            # if time.time() - self._prev_callback_timestamp < _MIN_CALLBACK_INTERVAL:
            #     time.sleep(0.1)
            #     continue
            self.flush()
            time.sleep(_MIN_CALLBACK_INTERVAL)
            # self._prev_callback_timestamp = time.time()

    def _pipe_relay(self):
        while True:
            try:
                data = os.read(self._pipe_read_fd, 4096)
                if self._stopped.is_set():
                    return
            except OSError:
                return
            try:
                i = self._orig_src.write(data)
                if i is not None:  # python 3 w/ unbuffered i/o: we need to keep writing
                    while i < len(data):
                        i += self._orig_src.write(data[i:])
                self.src_wrapped_stream.flush()
            except OSError:
                return
            try:
                self._emulator.write(data.decode("utf-8"))
            except UnicodeDecodeError:
                pass  # TODO(frz): partial unicode character?
