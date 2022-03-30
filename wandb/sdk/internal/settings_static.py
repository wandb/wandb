"""
static settings.
"""
from typing import Any, Dict, Iterable, Optional, Tuple, Union

SettingsDict = Dict[str, Union[str, float, Tuple, None]]


class SettingsStatic:
    # TODO(jhr): figure out how to share type defs with sdk/wandb_settings.py
    _offline: "Optional[bool]"
    _disable_stats: "Optional[bool]"
    _disable_meta: "Optional[bool]"
    _start_time: float
    _start_datetime: str
    files_dir: str
    log_internal: str
    _internal_check_process: bool
    is_local: "Optional[bool]"
    _colab: "Optional[bool]"
    _jupyter: "Optional[bool]"
    _require_service: "Optional[str]"
    resume: "Optional[str]"
    program: "Optional[str]"
    silent: "Optional[bool]"
    email: "Optional[str]"

    # TODO(jhr): clean this up, it is only in SettingsStatic and not in Settings
    _log_level: int

    def __init__(self, d: "SettingsDict") -> None:
        object.__setattr__(self, "__dict__", d)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Error: SettingsStatic is a readonly object")

    def __setitem__(self, key: str, val: object) -> None:
        raise AttributeError("Error: SettingsStatic is a readonly object")

    def keys(self) -> "Iterable[str]":
        return self.__dict__.keys()

    def items(self) -> "Iterable[Any]":
        return self.__dict__.items()

    def __getitem__(self, key: str) -> "Any":
        return self.__dict__[key]

    def __str__(self) -> str:
        return str(self.__dict__)
