from typing import Any, Dict, Iterable, Optional, Tuple, Union

from wandb.proto import wandb_settings_pb2

SettingsDict = Dict[str, Union[str, float, Tuple, None]]


class SettingsStatic:
    proto: wandb_settings_pb2.Settings

    def __init__(self, proto: wandb_settings_pb2.Settings) -> None:
        object.__setattr__(self, "proto", proto)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Error: SettingsStatic is a readonly object")

    def __setitem__(self, key: str, val: object) -> None:
        raise AttributeError("Error: SettingsStatic is a readonly object")

    def keys(self) -> "Iterable[str]":
        return (
            k
            for k in self.proto.DESCRIPTOR.fields_by_name.keys()
            if self.proto.HasField(k)
        )

    # def items(self) -> "Iterable[Any]":
    #     return self.proto.DESCRIPTOR.fields_by_name.items()

    def __getitem__(self, key: str) -> "Any":
        return getattr(self.proto, key)

    def __str__(self) -> str:
        return self.proto.__str__()

    def __contains__(self, key: str) -> bool:
        return key in self.keys()

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        return getattr(self.proto, key, default)
