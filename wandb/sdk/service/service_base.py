"""Base service abstract class.

Derived classes for socket service interfaces classes should implement
abstract methods.
"""

from abc import abstractmethod
from typing import TYPE_CHECKING, Optional

from wandb.proto import wandb_server_pb2 as spb

if TYPE_CHECKING:
    from wandb.proto import wandb_settings_pb2


class ServiceInterface:
    def __init__(self) -> None:
        pass

    @abstractmethod
    def get_transport(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def _svc_inform_init(
        self, settings: "wandb_settings_pb2.Settings", run_id: str
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def _svc_inform_start(
        self, settings: "wandb_settings_pb2.Settings", run_id: str
    ) -> None:
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
