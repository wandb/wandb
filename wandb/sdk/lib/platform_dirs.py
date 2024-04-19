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
    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    return Path(xdg_data_home or (Path.home() / ".local" / "share")) / "wandb"


def unix_user_cache_dir() -> Path:
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME", "").strip()
    return Path(xdg_cache_home or (Path.home() / ".cache")) / "wandb"


class LocalAppData:
    FOLDER_ID = 28
    ENV_VAR = "LOCALAPPDATA"
    REG_KEY = "Local AppData"


def windows_user_data_dir() -> Path:
    return Path(get_windows_local_appdata_dir()) / "wandb" / "wandb"


def windows_user_cache_dir() -> Path:
    return Path(get_windows_local_appdata_dir()) / "wandb" / "wandb" / "Cache"


def get_windows_local_appdata_dir() -> str:
    if hasattr(ctypes, "windll"):
        return get_win_folder_via_ctypes()

    try:
        import winreg  # noqa: PLC0415

        key = winreg.OpenKey(  # type: ignore[attr-defined]
            winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        )
        directory, _ = winreg.QueryValueEx(  # type: ignore[attr-defined]
            key, LocalAppData.REG_KEY
        )
        return directory

    except ImportError:
        environ = os.environ.get(LocalAppData.ENV_VAR)
        if environ:
            return environ

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
