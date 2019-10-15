"""
Windows-related compatibility helpers.
"""
import re
import ctypes
import subprocess
import platform
if platform.system() == "Windows":
    import msvcrt
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


DUPLICATE_SAME_ACCESS = 0x2
#https://gist.github.com/njsmith/211cce1d8583626dd945
#https://www.digitalenginesoftware.com/blog/archives/47-Passing-pipes-to-subprocesses-in-Python-in-Windows.html


def GetCurrentProcess():
    func = ctypes.windll.kernel32.GetCurrentProcess
    func.argtypes = []
    func.restype = ctypes.wintypes.HANDLE
    return func()


def CloseHandle(handle):
    func = ctypes.windll.kernel32.CloseHandle
    func.argtypes = [ctypes.wintypes.HANDLE]
    func.restype = ctypes.wintypes.BOOL
    return func(handle)


def DuplicateHandle(*args):
    # https://msdn.microsoft.com/en-us/library/windows/desktop/ms724251%28v=vs.85%29.aspx
    handle = ctypes.wintypes.HANDLE(-1)
    func = ctypes.windll.kernel32.DuplicateHandle
    func.argtypes = [
        # hSourceProcessHandle
        ctypes.wintypes.HANDLE,
        # hSourceHandle
        ctypes.wintypes.HANDLE,
        # hTargetProcessHandle
        ctypes.wintypes.HANDLE,
        # lpTargetHandle
        ctypes.wintypes.LPHANDLE,
        # dwDesiredAccess
        ctypes.wintypes.DWORD,
        # bInheritHandle
        ctypes.wintypes.BOOL,
        # dwOptions
        ctypes.wintypes.DWORD,
    ]
    func.restype = ctypes.wintypes.BOOL
    args = args[:3] + (ctypes.byref(handle),) + args[3:]
    res = func(*args)
    return handle

# TODO: see https://stackoverflow.com/questions/35772001/how-to-handle-the-signal-in-python-on-windows-machine
