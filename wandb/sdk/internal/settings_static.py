from dataclasses import fields
from typing import Any, Iterable

from wandb.proto import wandb_settings_pb2
from wandb.sdk.wandb_settings import SettingsData


class SettingsStatic(SettingsData):
    """A readonly object that wraps a protobuf Settings message.

    Implements the mapping protocol, so you can access settings as
    attributes or items.
    """

    def __init__(self, proto: wandb_settings_pb2.Settings) -> None:
        for field in fields(SettingsData):
            key = field.name
            if proto.HasField(key):  # type: ignore[arg-type]
                value = getattr(proto, key).value
                object.__setattr__(self, key, value)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Error: SettingsStatic is a readonly object")

    def __setitem__(self, key: str, val: object) -> None:
        raise AttributeError("Error: SettingsStatic is a readonly object")

    def keys(self) -> "Iterable[str]":
        return self.__dict__.keys()

    def __getitem__(self, key: str) -> Any:
        return self.__dict__[key]

    def __getattr__(self, name: str) -> Any:
        try:
            return self.__dict__[name]
        except KeyError:
            raise AttributeError(f"SettingsStatic has no attribute {name}")

    def __str__(self) -> str:
        return str(self.__dict__)

    def __contains__(self, key: str) -> bool:
        return key in self.__dict__
