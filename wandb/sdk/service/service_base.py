"""Base service abstract class.

Derived classes for socket service interfaces classes should implement
abstract methods.
"""

from abc import abstractmethod
from typing import Optional

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.wandb_settings import Settings


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
    def _svc_inform_broadcast(self, record: pb.Record, subscription_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def _svc_inform_subscribe(self, run_id: str, subscription_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def _svc_inform_unsubscribe(self, run_id: str, subscription_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def _svc_notify_read(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def _svc_connect(self, port: int) -> None:
        raise NotImplementedError
