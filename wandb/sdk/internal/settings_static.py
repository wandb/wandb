from typing import Any, Iterable

from wandb.proto import wandb_settings_pb2


class SettingsStatic:
    proto: wandb_settings_pb2.Settings

    def __init__(self, proto: wandb_settings_pb2.Settings) -> None:
        object.__setattr__(self, "proto", proto)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Error: SettingsStatic is a readonly object")

    def __setitem__(self, key: str, val: object) -> None:
        raise AttributeError("Error: SettingsStatic is a readonly object")

    def keys(self) -> "Iterable[str]":
        return (k for k in self.proto.DESCRIPTOR.fields_by_name.keys())

    def __getitem__(self, key: str) -> Any:
        if key not in self.keys():
            raise KeyError(key)
        return getattr(self.proto, key).value if self.proto.HasField(key) else None  # type: ignore [arg-type]

    def __getattr__(self, name: str) -> Any:
        if name not in self.keys():
            raise AttributeError(f"SettingsStatic has no attribute {name}")
        return getattr(self.proto, name).value if self.proto.HasField(name) else None  # type: ignore [arg-type]

    def __str__(self) -> str:
        return self.proto.__str__()

    def __contains__(self, key: str) -> bool:
        return key in self.keys()
