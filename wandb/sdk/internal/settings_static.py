from dataclasses import fields
from typing import Any, Iterable, Sequence, Tuple

from wandb.proto import wandb_settings_pb2
from wandb.sdk.lib import RunMoment
from wandb.sdk.wandb_settings import SettingsData


class SettingsStatic(SettingsData):
    """A readonly object that wraps a protobuf Settings message.

    Implements the mapping protocol, so you can access settings as
    attributes or items.
    """

    def __init__(self, proto: wandb_settings_pb2.Settings) -> None:
        self._from_proto(proto)
        object.__setattr__(self, "_proto", proto)

    def _from_proto(self, proto: wandb_settings_pb2.Settings) -> None:
        forks_specified: list[str] = []
        for field in fields(SettingsData):
            key = field.name
            value: Any = None
            if key == "_stats_open_metrics_filters":
                # todo: it's an underscored field, refactor into
                #  something more elegant?
                # I'm really about this. It's ugly, but it works.
                # Do not try to repeat this at home.
                value_type = getattr(proto, key).WhichOneof("value")
                if value_type == "sequence":
                    value = list(getattr(proto, key).sequence.value)
                elif value_type == "mapping":
                    unpacked_mapping = {}
                    for outer_key, outer_value in getattr(
                        proto, key
                    ).mapping.value.items():
                        unpacked_inner = {}
                        for inner_key, inner_value in outer_value.value.items():
                            unpacked_inner[inner_key] = inner_value
                        unpacked_mapping[outer_key] = unpacked_inner
                    value = unpacked_mapping
            elif key == "fork_from" or key == "resume_from":
                value = getattr(proto, key)
                if value.run:
                    value = RunMoment(
                        run=value.run, value=value.value, metric=value.metric
                    )
                    forks_specified.append(key)
                else:
                    value = None
            else:
                if proto.HasField(key):  # type: ignore [arg-type]
                    value = getattr(proto, key).value
                    if field.type == Sequence[str]:
                        value = list(value)
                    elif field.type == Tuple[str]:
                        value = tuple(value)
                else:
                    value = None
            object.__setattr__(self, key, value)

        if len(forks_specified) > 1:
            raise ValueError(
                "Only one of fork_from or resume_from can be specified, not both"
            )

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
