"""Base service abstract class.

Derived classes for grpc and socket service interfaces classes should implement
abstract methods.
"""

from abc import abstractmethod
import datetime
import enum
from typing import Any, Dict
from typing import TYPE_CHECKING

from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.wandb_settings import Settings

if TYPE_CHECKING:
    from google.protobuf.internal.containers import MessageMap


def _pbmap_apply_dict(
    m: "MessageMap[str, spb.SettingsValue]", d: Dict[str, Any]
) -> None:
    for k, v in d.items():
        if isinstance(v, datetime.datetime):
            continue
        if isinstance(v, enum.Enum):
            continue
        sv = spb.SettingsValue()
        if v is None:
            sv.null_value = True
        elif isinstance(v, int):
            sv.int_value = v
        elif isinstance(v, float):
            sv.float_value = v
        elif isinstance(v, str):
            sv.string_value = v
        elif isinstance(v, bool):
            sv.bool_value = v
        elif isinstance(v, tuple):
            sv.tuple_value.string_values.extend(v)
        m[k].CopyFrom(sv)


class ServiceInterface:
    def __init__(self) -> None:
        pass

    @abstractmethod
    def get_transport(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def _svc_inform_init(self, settings: Settings, run_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def _svc_inform_attach(self, attach_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def _svc_inform_finish(self, run_id: str = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def _svc_inform_teardown(self, exit_code: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def _svc_connect(self, port: int) -> None:
        raise NotImplementedError
