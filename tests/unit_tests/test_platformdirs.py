from __future__ import annotations

import pytest
from wandb import _platformdirs


def _clear_dir_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "WIN_PD_OVERRIDE_LOCAL_APPDATA",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("platform", "environ", "expected_data_dir", "expected_cache_dir"),
    [
        (
            "linux",
            {"HOME": "/home/alice"},
            "/home/alice/.local/share/wandb",
            "/home/alice/.cache/wandb",
        ),
        (
            "linux",
            {
                "HOME": "/home/alice",
                "XDG_DATA_HOME": "/data",
                "XDG_CACHE_HOME": "/cache",
            },
            "/data/wandb",
            "/cache/wandb",
        ),
        (
            "darwin",
            {"HOME": "/Users/alice"},
            "/Users/alice/Library/Application Support/wandb",
            "/Users/alice/Library/Caches/wandb",
        ),
        (
            "darwin",
            {
                "HOME": "/Users/alice",
                "XDG_DATA_HOME": "/data",
                "XDG_CACHE_HOME": "/cache",
            },
            "/data/wandb",
            "/cache/wandb",
        ),
        (
            "win32",
            {
                "LOCALAPPDATA": r"C:\Users\Alice\AppData\Local",
                "XDG_DATA_HOME": "/ignored",
                "XDG_CACHE_HOME": "/ignored",
            },
            r"C:\Users\Alice\AppData\Local\wandb\wandb",
            r"C:\Users\Alice\AppData\Local\wandb\wandb\Cache",
        ),
        (
            "win32",
            {"WIN_PD_OVERRIDE_LOCAL_APPDATA": r"D:\LocalAppData"},
            r"D:\LocalAppData\wandb\wandb",
            r"D:\LocalAppData\wandb\wandb\Cache",
        ),
    ],
)
def test_user_data_and_cache_dirs(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    environ: dict[str, str],
    expected_data_dir: str,
    expected_cache_dir: str,
) -> None:
    monkeypatch.setattr(_platformdirs.sys, "platform", platform)
    _clear_dir_env(monkeypatch)
    for name, value in environ.items():
        monkeypatch.setenv(name, value)

    assert _platformdirs.user_data_dir("wandb") == expected_data_dir
    assert _platformdirs.user_cache_dir("wandb") == expected_cache_dir


def test_windows_local_app_data_prefers_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> str:
        raise AssertionError("fallback should not be called")

    monkeypatch.setenv("WIN_PD_OVERRIDE_LOCAL_APPDATA", r"D:\Override")
    monkeypatch.setattr(_platformdirs, "_windows_known_folder_local_app_data", fail)
    monkeypatch.setattr(_platformdirs, "_windows_registry_local_app_data", fail)
    monkeypatch.setattr(_platformdirs, "_windows_env_local_app_data", fail)

    assert _platformdirs._windows_local_app_data() == r"D:\Override"


def test_windows_local_app_data_prefers_known_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WIN_PD_OVERRIDE_LOCAL_APPDATA", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Env")
    monkeypatch.setattr(
        _platformdirs, "_windows_known_folder_local_app_data", lambda: r"D:\Known"
    )
    monkeypatch.setattr(
        _platformdirs, "_windows_registry_local_app_data", lambda: r"E:\Registry"
    )

    assert _platformdirs._windows_local_app_data() == r"D:\Known"


def test_windows_local_app_data_falls_back_to_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> str:
        raise OSError("unavailable")

    monkeypatch.delenv("WIN_PD_OVERRIDE_LOCAL_APPDATA", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Env")
    monkeypatch.setattr(
        _platformdirs, "_windows_known_folder_local_app_data", unavailable
    )
    monkeypatch.setattr(
        _platformdirs, "_windows_registry_local_app_data", lambda: r"D:\Registry"
    )

    assert _platformdirs._windows_local_app_data() == r"D:\Registry"


def test_windows_local_app_data_falls_back_to_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> str:
        raise OSError("unavailable")

    monkeypatch.delenv("WIN_PD_OVERRIDE_LOCAL_APPDATA", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Env")
    monkeypatch.setattr(
        _platformdirs, "_windows_known_folder_local_app_data", unavailable
    )
    monkeypatch.setattr(_platformdirs, "_windows_registry_local_app_data", unavailable)

    assert _platformdirs._windows_local_app_data() == r"C:\Env"
