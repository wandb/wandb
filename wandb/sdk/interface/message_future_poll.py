"""MessageFuturePoll - Derived from MessageFuture but implementing polling loop.

MessageFuture represents a message result of an asynchronous operation.

MessageFuturePoll implements a polling loop to periodically query for a
completed async operation.

"""

import time
from typing import Any, Optional

from wandb.proto import wandb_internal_pb2 as pb

from .message_future import MessageFuture


class MessageFuturePoll(MessageFuture):
    _fn: Any
    _xid: str

    def __init__(self, fn: Any, xid: str) -> None:
        super().__init__()
        self._fn = fn
        self._xid = xid

    def get(self, timeout: Optional[int] = None) -> Optional[pb.Result]:
        self._poll(timeout=timeout)
        if self._object_ready.is_set():
            return self._object
        return None

    def _poll(self, timeout: Optional[int] = None) -> None:
        if self._object_ready.is_set():
            return
        done = False
        start_time = time.time()
        sleep_time = 0.5
        while not done:
            result = self._fn(xid=self._xid)
            if result:
                self._set_object(result)
                done = True
                continue
            now_time = time.time()
            if timeout and start_time - now_time > timeout:
                done = True
                continue
            time.sleep(sleep_time)
            sleep_time = min(sleep_time * 2, 5)
