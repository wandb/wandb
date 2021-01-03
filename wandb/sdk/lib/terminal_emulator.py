import pyte
import re
from wcwidth import wcwidth
import unicodedata
import os
import itertools
from pyte.control import CSI
from pyte.escape import SGR

# Reverse graphic maps
FG = {v: str(k) for k, v in itertools.chain(pyte.graphics.FG.items(), pyte.graphics.FG_AIXTERM.items())}
BG = {v: str(k) for k, v in itertools.chain(pyte.graphics.BG.items(), pyte.graphics.BG_AIXTERM.items())}
FG_256 = str(pyte.graphics.FG_256)  # 38
BG_256 = str(pyte.graphics.BG_256)  # 48
FG_BG_256 = {x: str(i) for (i, x) in enumerate(pyte.graphics.FG_BG_256)}
TEXT = {v: str(k) for k, v in pyte.graphics.TEXT.items()}
BIT_256 = ";5;"
BIT_24 = ";2;"


def _hex_string_to_int_string(h):
    return ";".join(str(int(h[i: i + 2], 16)) for i in range(0, len(h), 2))


class InfiniteScreen(pyte.Screen):
    def __init__(self):
        super(InfiniteScreen, self).__init__(columns=5, lines=5)
        self._prev_num_lines = None
        self._prev_last_line = None
        if os.name != 'nt':
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
            ''.join(self.buffer[i][j].data for j in range(self._len(i))) for i in range(self._lines)
        ]

    def _get_line(self, line, formatting=True):
        if not formatting:
            return ''.join([self.buffer[line][i].data for i in range(self._len(line))])
        ret = ''
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
                        ret += CSI + FG_256 + BIT_24 + _hex_string_to_int_string(c.fg) + SGR
            if c.bg != prev_char.bg:
                bg_code = BG.get(c.bg)
                if bg_code:
                    ret += CSI + bg_code + SGR
                else:
                    bg_code = FG_BG_256.get(c.bg)
                    if bg_code:
                        ret += CSI + BG_256 + BIT_256 + bg_code + SGR
                    else:
                        ret += CSI + BG_256 + BIT_24 + _hex_string_to_int_string(c.bg) + SGR
            for i, attr in list(enumerate(c._fields))[3:]: # skip data, fg, bg
                if c[i] != prev_char[i]:
                    ret += CSI + TEXT[('-', '+')[c[i]] + attr] + SGR
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
        else:
            curr_line = self._get_line(self._prev_num_lines - 1)
            if curr_line == self._prev_last_line:
                ret = os.linesep.join(map(self._get_line, range(self._prev_num_lines, num_lines)))
            else:
                ret = '\r' + os.linesep.join(map(self._get_line, range(self._prev_num_lines - 1, num_lines)))
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
                return ''
        return screen.pop_diff()

    def reset(self):
        self._screen.reset()
