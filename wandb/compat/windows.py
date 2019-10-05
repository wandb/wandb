"""
Windows-related compatibility helpers.
"""
import re
import ctypes

_find_unsafe = re.compile(r'[\s<>|&^]').search


def quote_arg(s):
    """Based on shlex.quote in the standard library."""
    if not s:
        return '""'
    if _find_unsafe(s) is None:
        return s
    if s.startswith('"') and s.endswith('"'):
        return s

    # If we found an unsafe character, escape with double quotes.
    return '"' + s + '"'


def pid_running(pid):
    kernel32 = ctypes.windll.kernel32
    SYNCHRONIZE = 0x100000

    process = kernel32.OpenProcess(SYNCHRONIZE, 0, pid)
    if process != 0:
        kernel32.CloseHandle(process)
        return True
    else:
        return False
