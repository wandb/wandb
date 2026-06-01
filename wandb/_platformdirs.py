"""Small platform directory helpers for W&B.

Portions of the Windows LocalAppData resolution are adapted from platformdirs
4.10.0, `platformdirs/windows.py`: https://github.com/tox-dev/platformdirs

MIT License

Copyright (c) 2010-202x The platformdirs developers

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import ntpath
import os
import sys

_WINDOWS_LOCAL_APPDATA_GUID = "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}"
_KF_FLAG_DONT_VERIFY = 0x00004000


def user_data_dir(app_name: str) -> str:
    if sys.platform == "win32":
        return ntpath.join(_windows_local_app_data(), app_name, app_name)

    if xdg_dir := _xdg_dir("XDG_DATA_HOME", app_name):
        return xdg_dir

    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Application Support/{app_name}")

    return os.path.join(os.path.expanduser("~/.local/share"), app_name)


def user_cache_dir(app_name: str) -> str:
    if sys.platform == "win32":
        return ntpath.join(_windows_local_app_data(), app_name, app_name, "Cache")

    if xdg_dir := _xdg_dir("XDG_CACHE_HOME", app_name):
        return xdg_dir

    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Caches/{app_name}")

    return os.path.join(os.path.expanduser("~/.cache"), app_name)


def _xdg_dir(env_var: str, app_name: str) -> str | None:
    path = os.environ.get(env_var, "").strip()
    if path:
        return os.path.join(path, app_name)
    return None


def _windows_local_app_data() -> str:
    override = os.environ.get("WIN_PD_OVERRIDE_LOCAL_APPDATA", "").strip()
    if override:
        return ntpath.normpath(override)

    for get_dir in (
        _windows_known_folder_local_app_data,
        _windows_registry_local_app_data,
        _windows_env_local_app_data,
    ):
        try:
            path = get_dir()
            if path:
                return ntpath.normpath(path)
        except (AttributeError, ImportError, OSError, ValueError):
            pass

    raise ValueError("Unable to find Windows LocalAppData directory.")


def _windows_known_folder_local_app_data() -> str:
    if sys.platform != "win32":
        raise OSError("Windows known folders are only available on Windows.")

    from ctypes import (
        HRESULT,
        POINTER,
        Structure,
        WinDLL,
        byref,
        create_unicode_buffer,
        wintypes,
    )

    class _GUID(Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        ]

    ole32 = WinDLL("ole32")
    ole32.CLSIDFromString.restype = HRESULT
    ole32.CLSIDFromString.argtypes = [wintypes.LPCOLESTR, POINTER(_GUID)]
    ole32.CoTaskMemFree.restype = None
    ole32.CoTaskMemFree.argtypes = [wintypes.LPVOID]

    shell32 = WinDLL("shell32")
    shell32.SHGetKnownFolderPath.restype = HRESULT
    shell32.SHGetKnownFolderPath.argtypes = [
        POINTER(_GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        POINTER(wintypes.LPWSTR),
    ]

    guid = _GUID()
    if ole32.CLSIDFromString(_WINDOWS_LOCAL_APPDATA_GUID, byref(guid)) != 0:
        raise OSError("Unable to resolve LocalAppData GUID.")

    path_ptr = wintypes.LPWSTR()
    result = shell32.SHGetKnownFolderPath(
        byref(guid), _KF_FLAG_DONT_VERIFY, None, byref(path_ptr)
    )
    try:
        if result != 0 or path_ptr.value is None:
            raise OSError("Unable to resolve LocalAppData known folder.")
        path = path_ptr.value
    finally:
        if path_ptr:
            ole32.CoTaskMemFree(path_ptr)

    if any(ord(char) > 255 for char in path):
        kernel32 = WinDLL("kernel32")
        kernel32.GetShortPathNameW.restype = wintypes.DWORD
        kernel32.GetShortPathNameW.argtypes = [
            wintypes.LPWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        buf = create_unicode_buffer(1024)
        if kernel32.GetShortPathNameW(path, buf, 1024):
            path = buf.value

    return path


def _windows_registry_local_app_data() -> str:
    if sys.platform != "win32":
        raise OSError("Windows registry is only available on Windows.")

    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
    ) as key:
        path, _ = winreg.QueryValueEx(key, "Local AppData")
    return str(path)


def _windows_env_local_app_data() -> str:
    path = os.environ.get("LOCALAPPDATA")
    if not path:
        raise ValueError("Unset environment variable: LOCALAPPDATA")
    return path
