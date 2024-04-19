"""Platform-dependent directory paths.

Adapted from the [platformdirs library](https://github.com/platformdirs/platformdirs/),
simplified for the few directories we use and made specific to the wandb app.
"""

import ctypes
import os
import platform
from pathlib import Path


def user_data_dir() -> Path:
    if platform.system() == "Windows":
        return windows_user_data_dir()
    elif platform.system() == "Darwin":
        return macos_user_data_dir()
    elif platform.system() == "Linux":
        return unix_user_data_dir()
    raise RuntimeError(f"Unsupported platform: {platform.system()}")


def user_cache_dir() -> Path:
    if platform.system() == "Windows":
        return windows_user_cache_dir()
    elif platform.system() == "Darwin":
        return macos_user_cache_dir()
    elif platform.system() == "Linux":
        return unix_user_cache_dir()
    raise RuntimeError(f"Unsupported platform: {platform.system()}")


def macos_user_data_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "wandb"


def macos_user_cache_dir() -> Path:
    return Path.home() / "Library" / "Caches" / "wandb"


def unix_user_data_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME", "")
    if not data_home.strip():
        data_home = Path.home() / ".local" / "share"
    return data_home / "wandb"


def unix_user_cache_dir() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME", "")
    if not cache_home.strip():
        cache_home = Path.home() / ".cache"
    return cache_home / "wandb"


class LocalAppData:
    FOLDER_ID = 28
    ENV_VAR = "LOCALAPPDATA"
    REG_KEY = "Local AppData"


def windows_user_data_dir() -> Path:
    return get_windows_local_appdata_dir() / "wandb" / "wandb"


def windows_user_cache_dir() -> Path:
    return get_windows_local_appdata_dir() / "wandb" / "wandb" / "Cache"


def get_windows_local_appdata_dir() -> Path:
    if hasattr(ctypes, "windll"):
        return get_win_folder_via_ctypes()

    try:
        import winreg  # noqa: PLC0415

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        )
        directory, _ = winreg.QueryValueEx(key, LocalAppData.REG_KEY)
        return Path(directory)

    except ImportError:
        environ = os.environ.get(LocalAppData.ENV_VAR)
        if environ:
            return Path(environ)

    raise RuntimeError("Failed to determine Windows user data directory.")


def get_win_folder_via_ctypes() -> str:
    buf = ctypes.create_unicode_buffer(1024)
    windll = getattr(ctypes, "windll")  # noqa: B009 # avoid false mypy positive
    windll.shell32.SHGetFolderPathW(None, LocalAppData.FOLDER_ID, None, 0, buf)

    # Downgrade to short path name if it has high-bit chars.
    if any(ord(c) > 255 for c in buf):  # noqa: PLR2004
        buf2 = ctypes.create_unicode_buffer(1024)
        if windll.kernel32.GetShortPathNameW(buf.value, buf2, 1024):
            buf = buf2

    return buf.value
