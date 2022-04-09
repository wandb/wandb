"""MessageFuture - represents a message result of an asynchronous operation

Base class MessageFuture for MessageFutureObject and MessageFuturePoll

"""

from abc import abstractmethod
import threading
from typing import Optional

from wandb.proto import wandb_internal_pb2 as pb


class MessageFuture:
    _object: Optional[pb.Result]

    def __init__(self) -> None:
        self._object = None
        self._object_ready = threading.Event()

    def _set_object(self, obj: pb.Result) -> None:
        self._object = obj
        self._object_ready.set()

    @abstractmethod
    def get(self, timeout: int = None) -> Optional[pb.Result]:
        raise NotImplementedError
