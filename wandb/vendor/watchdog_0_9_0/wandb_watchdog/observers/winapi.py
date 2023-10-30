#!/usr/bin/env python
# -*- coding: utf-8 -*-
# winapi.py: Windows API-Python interface (removes dependency on pywin32)
#
# Copyright (C) 2007 Thomas Heller <theller@ctypes.org>
# Copyright (C) 2010 Will McGugan <will@willmcgugan.com>
# Copyright (C) 2010 Ryan Kelly <ryan@rfk.id.au>
# Copyright (C) 2010 Yesudeep Mangalapilly <yesudeep@gmail.com>
# Copyright (C) 2014 Thomas Amland
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and / or other materials provided with the distribution.
# * Neither the name of the organization nor the names of its contributors may
#   be used to endorse or promote products derived from this software without
#   specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# Portions of this code were taken from pyfilesystem, which uses the above
# new BSD license.

from __future__ import with_statement

import ctypes.wintypes
from functools import reduce

try:
    LPVOID = ctypes.wintypes.LPVOID
except AttributeError:
    # LPVOID wasn't defined in Py2.5, guess it was introduced in Py2.6
    LPVOID = ctypes.c_void_p

# Invalid handle value.
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# File notification contants.
FILE_NOTIFY_CHANGE_FILE_NAME = 0x01
FILE_NOTIFY_CHANGE_DIR_NAME = 0x02
FILE_NOTIFY_CHANGE_ATTRIBUTES = 0x04
FILE_NOTIFY_CHANGE_SIZE = 0x08
FILE_NOTIFY_CHANGE_LAST_WRITE = 0x010
FILE_NOTIFY_CHANGE_LAST_ACCESS = 0x020
FILE_NOTIFY_CHANGE_CREATION = 0x040
FILE_NOTIFY_CHANGE_SECURITY = 0x0100

FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_LIST_DIRECTORY = 1
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
FILE_SHARE_DELETE = 0x04
OPEN_EXISTING = 3

# File action constants.
FILE_ACTION_CREATED = 1
FILE_ACTION_DELETED = 2
FILE_ACTION_MODIFIED = 3
FILE_ACTION_RENAMED_OLD_NAME = 4
FILE_ACTION_RENAMED_NEW_NAME = 5
FILE_ACTION_OVERFLOW = 0xFFFF

# Aliases
FILE_ACTION_ADDED = FILE_ACTION_CREATED
FILE_ACTION_REMOVED = FILE_ACTION_DELETED

THREAD_TERMINATE = 0x0001

# IO waiting constants.
WAIT_ABANDONED = 0x00000080
WAIT_IO_COMPLETION = 0x000000C0
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102

# Error codes
ERROR_OPERATION_ABORTED = 995


class OVERLAPPED(ctypes.Structure):
    _fields_ = [('Internal', LPVOID),
                ('InternalHigh', LPVOID),
                ('Offset', ctypes.wintypes.DWORD),
                ('OffsetHigh', ctypes.wintypes.DWORD),
                ('Pointer', LPVOID),
                ('hEvent', ctypes.wintypes.HANDLE),
                ]


def _errcheck_bool(value, func, args):
    if not value:
        raise ctypes.WinError
    return args


def _errcheck_handle(value, func, args):
    if not value:
        raise ctypes.WinError
    if value == INVALID_HANDLE_VALUE:
        raise ctypes.WinError
    return args


def _errcheck_dword(value, func, args):
    if value == 0xFFFFFFFF:
        raise ctypes.WinError
    return args


ReadDirectoryChangesW = ctypes.windll.kernel32.ReadDirectoryChangesW
ReadDirectoryChangesW.restype = ctypes.wintypes.BOOL
ReadDirectoryChangesW.errcheck = _errcheck_bool
ReadDirectoryChangesW.argtypes = (
    ctypes.wintypes.HANDLE,  # hDirectory
    LPVOID,  # lpBuffer
    ctypes.wintypes.DWORD,  # nBufferLength
    ctypes.wintypes.BOOL,  # bWatchSubtree
    ctypes.wintypes.DWORD,  # dwNotifyFilter
    ctypes.POINTER(ctypes.wintypes.DWORD),  # lpBytesReturned
    ctypes.POINTER(OVERLAPPED),  # lpOverlapped
    LPVOID  # FileIOCompletionRoutine # lpCompletionRoutine
)

CreateFileW = ctypes.windll.kernel32.CreateFileW
CreateFileW.restype = ctypes.wintypes.HANDLE
CreateFileW.errcheck = _errcheck_handle
CreateFileW.argtypes = (
    ctypes.wintypes.LPCWSTR,  # lpFileName
    ctypes.wintypes.DWORD,  # dwDesiredAccess
    ctypes.wintypes.DWORD,  # dwShareMode
    LPVOID,  # lpSecurityAttributes
    ctypes.wintypes.DWORD,  # dwCreationDisposition
    ctypes.wintypes.DWORD,  # dwFlagsAndAttributes
    ctypes.wintypes.HANDLE  # hTemplateFile
)

CloseHandle = ctypes.windll.kernel32.CloseHandle
CloseHandle.restype = ctypes.wintypes.BOOL
CloseHandle.argtypes = (
    ctypes.wintypes.HANDLE,  # hObject
)

CancelIoEx = ctypes.windll.kernel32.CancelIoEx
CancelIoEx.restype = ctypes.wintypes.BOOL
CancelIoEx.errcheck = _errcheck_bool
CancelIoEx.argtypes = (
    ctypes.wintypes.HANDLE,  # hObject
    ctypes.POINTER(OVERLAPPED)  # lpOverlapped
)

CreateEvent = ctypes.windll.kernel32.CreateEventW
CreateEvent.restype = ctypes.wintypes.HANDLE
CreateEvent.errcheck = _errcheck_handle
CreateEvent.argtypes = (
    LPVOID,  # lpEventAttributes
    ctypes.wintypes.BOOL,  # bManualReset
    ctypes.wintypes.BOOL,  # bInitialState
    ctypes.wintypes.LPCWSTR,  # lpName
)

SetEvent = ctypes.windll.kernel32.SetEvent
SetEvent.restype = ctypes.wintypes.BOOL
SetEvent.errcheck = _errcheck_bool
SetEvent.argtypes = (
    ctypes.wintypes.HANDLE,  # hEvent
)

WaitForSingleObjectEx = ctypes.windll.kernel32.WaitForSingleObjectEx
WaitForSingleObjectEx.restype = ctypes.wintypes.DWORD
WaitForSingleObjectEx.errcheck = _errcheck_dword
WaitForSingleObjectEx.argtypes = (
    ctypes.wintypes.HANDLE,  # hObject
    ctypes.wintypes.DWORD,  # dwMilliseconds
    ctypes.wintypes.BOOL,  # bAlertable
)

CreateIoCompletionPort = ctypes.windll.kernel32.CreateIoCompletionPort
CreateIoCompletionPort.restype = ctypes.wintypes.HANDLE
CreateIoCompletionPort.errcheck = _errcheck_handle
CreateIoCompletionPort.argtypes = (
    ctypes.wintypes.HANDLE,  # FileHandle
    ctypes.wintypes.HANDLE,  # ExistingCompletionPort
    LPVOID,  # CompletionKey
    ctypes.wintypes.DWORD,  # NumberOfConcurrentThreads
)

GetQueuedCompletionStatus = ctypes.windll.kernel32.GetQueuedCompletionStatus
GetQueuedCompletionStatus.restype = ctypes.wintypes.BOOL
GetQueuedCompletionStatus.errcheck = _errcheck_bool
GetQueuedCompletionStatus.argtypes = (
    ctypes.wintypes.HANDLE,  # CompletionPort
    LPVOID,  # lpNumberOfBytesTransferred
    LPVOID,  # lpCompletionKey
    ctypes.POINTER(OVERLAPPED),  # lpOverlapped
    ctypes.wintypes.DWORD,  # dwMilliseconds
)

PostQueuedCompletionStatus = ctypes.windll.kernel32.PostQueuedCompletionStatus
PostQueuedCompletionStatus.restype = ctypes.wintypes.BOOL
PostQueuedCompletionStatus.errcheck = _errcheck_bool
PostQueuedCompletionStatus.argtypes = (
    ctypes.wintypes.HANDLE,  # CompletionPort
    ctypes.wintypes.DWORD,  # lpNumberOfBytesTransferred
    ctypes.wintypes.DWORD,  # lpCompletionKey
    ctypes.POINTER(OVERLAPPED),  # lpOverlapped
)


class FILE_NOTIFY_INFORMATION(ctypes.Structure):
    _fields_ = [("NextEntryOffset", ctypes.wintypes.DWORD),
                ("Action", ctypes.wintypes.DWORD),
                ("FileNameLength", ctypes.wintypes.DWORD),
                #("FileName", (ctypes.wintypes.WCHAR * 1))]
                ("FileName", (ctypes.c_char * 1))]

LPFNI = ctypes.POINTER(FILE_NOTIFY_INFORMATION)


# We don't need to recalculate these flags every time a call is made to
# the win32 API functions.
WATCHDOG_FILE_FLAGS = FILE_FLAG_BACKUP_SEMANTICS
WATCHDOG_FILE_SHARE_FLAGS = reduce(
    lambda x, y: x | y, [
        FILE_SHARE_READ,
        FILE_SHARE_WRITE,
        FILE_SHARE_DELETE,
    ])
WATCHDOG_FILE_NOTIFY_FLAGS = reduce(
    lambda x, y: x | y, [
        FILE_NOTIFY_CHANGE_FILE_NAME,
        FILE_NOTIFY_CHANGE_DIR_NAME,
        FILE_NOTIFY_CHANGE_ATTRIBUTES,
        FILE_NOTIFY_CHANGE_SIZE,
        FILE_NOTIFY_CHANGE_LAST_WRITE,
        FILE_NOTIFY_CHANGE_SECURITY,
        FILE_NOTIFY_CHANGE_LAST_ACCESS,
        FILE_NOTIFY_CHANGE_CREATION,
    ])

BUFFER_SIZE = 2048

    
def _parse_event_buffer(readBuffer, nBytes):
    results = []
    while nBytes > 0:
        fni = ctypes.cast(readBuffer, LPFNI)[0]
        ptr = ctypes.addressof(fni) + FILE_NOTIFY_INFORMATION.FileName.offset
        #filename = ctypes.wstring_at(ptr, fni.FileNameLength)
        filename = ctypes.string_at(ptr, fni.FileNameLength)
        results.append((fni.Action, filename.decode('utf-16')))
        numToSkip = fni.NextEntryOffset
        if numToSkip <= 0:
            break
        readBuffer = readBuffer[numToSkip:]
        nBytes -= numToSkip  # numToSkip is long. nBytes should be long too.
    return results


def get_directory_handle(path):
    """Returns a Windows handle to the specified directory path."""
    return CreateFileW(path, FILE_LIST_DIRECTORY, WATCHDOG_FILE_SHARE_FLAGS,
                       None, OPEN_EXISTING, WATCHDOG_FILE_FLAGS, None)


def close_directory_handle(handle):
    try:
        CancelIoEx(handle, None)  # force ReadDirectoryChangesW to return
        CloseHandle(handle)       # close directory handle
    except WindowsError:
        try:
            CloseHandle(handle)   # close directory handle
        except:
            return


def read_directory_changes(handle, recursive):
    """Read changes to the directory using the specified directory handle.

    http://timgolden.me.uk/pywin32-docs/win32file__ReadDirectoryChangesW_meth.html
    """
    event_buffer = ctypes.create_string_buffer(BUFFER_SIZE)
    nbytes = ctypes.wintypes.DWORD()
    try:
        ReadDirectoryChangesW(handle, ctypes.byref(event_buffer),
                              len(event_buffer), recursive,
                              WATCHDOG_FILE_NOTIFY_FLAGS,
                              ctypes.byref(nbytes), None, None)
    except WindowsError as e:
        if e.winerror == ERROR_OPERATION_ABORTED:
            return [], 0
        raise e

    # Python 2/3 compat
    try:
        int_class = long
    except NameError:
        int_class = int
    return event_buffer.raw, int_class(nbytes.value)


class WinAPINativeEvent(object):
    def __init__(self, action, src_path):
        self.action = action
        self.src_path = src_path
    
    @property
    def is_added(self):
        return self.action == FILE_ACTION_CREATED
    
    @property
    def is_removed(self):
        return self.action == FILE_ACTION_REMOVED
    
    @property
    def is_modified(self):
        return self.action == FILE_ACTION_MODIFIED
    
    @property
    def is_renamed_old(self):
        return self.action == FILE_ACTION_RENAMED_OLD_NAME
    
    @property
    def is_renamed_new(self):
        return self.action == FILE_ACTION_RENAMED_NEW_NAME
    
    def __repr__(self):
        return ("<WinAPINativeEvent: action=%d, src_path=%r>" % (self.action, self.src_path))


def read_events(handle, recursive):
    buf, nbytes = read_directory_changes(handle, recursive)
    events = _parse_event_buffer(buf, nbytes)
    return [WinAPINativeEvent(action, path) for action, path in events]
