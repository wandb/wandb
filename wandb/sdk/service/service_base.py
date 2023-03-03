"""Base service abstract class.

Derived classes for grpc and socket service interfaces classes should implement
abstract methods.
"""

import datetime
import enum
from abc import abstractmethod
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, Dict, Optional

from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.wandb_settings import Settings

if TYPE_CHECKING:
    from google.protobuf.internal.containers import MessageMap


def _pbmap_apply_dict(
    m: "MessageMap[str, spb.SettingsValue]", d: Dict[str, Any]
) -> None:

    for k, v in d.items():
        if isinstance(v, enum.Enum):
            continue
        sv = spb.SettingsValue()
        if v is None:
            sv.null_value = True
        elif isinstance(
            v, bool
        ):  # order matters when using `isinstance` since it looks at all the subclasses and isinstance(True, int) will be true
            sv.bool_value = v
        elif isinstance(v, int):
            sv.int_value = v
        elif isinstance(v, float):
            sv.float_value = v
        elif isinstance(v, str):
            sv.string_value = v
        elif isinstance(v, Iterable) and not isinstance(v, (str, bytes, Mapping)):
            if all(isinstance(x, str) for x in v):  # Iterable[str]
                sv.tuple_value.string_values.extend(v)
        elif isinstance(v, Mapping):
            for kk, vv in v.items():
                if isinstance(vv, str):
                    # flat map
                    sv.map_value.map_values[kk] = vv
                elif isinstance(vv, Mapping):
                    # nested map
                    for kkk, vvv in vv.items():
                        sv.nested_map_value.nested_map_values[kk].map_values[kkk] = vvv

        elif isinstance(v, datetime.datetime):
            sv.timestamp_value = datetime.datetime.strftime(v, "%Y%m%d_%H%M%S")
        else:
            raise Exception("unsupported type")
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
    def _svc_inform_start(self, settings: Settings, run_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def _svc_inform_attach(self, attach_id: str) -> spb.ServerInformAttachResponse:
        raise NotImplementedError

    @abstractmethod
    def _svc_inform_finish(self, run_id: Optional[str] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def _svc_inform_teardown(self, exit_code: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def _svc_connect(self, port: int) -> None:
        raise NotImplementedError
