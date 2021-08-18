#
# -*- coding: utf-8 -*-
"""
static settings.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, Optional, Union

    SettingsDict = Dict[str, Union[str, float]]


class SettingsStatic(object):
    # TODO(jhr): figure out how to share type defs with sdk/wandb_settings.py
    _offline: "Optional[bool]"
    _disable_stats: "Optional[bool]"
    _disable_meta: "Optional[bool]"
    _start_time: float
    files_dir: str
    log_internal: str
    _internal_check_process: bool

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

    def __getitem__(self, key: str) -> "Any":
        return self.__dict__[key]

    def __str__(self) -> str:
        return str(self.__dict__)
