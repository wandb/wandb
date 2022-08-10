"""
intents.
"""

import secrets
import string
import time
from typing import Callable, Optional
from typing import TYPE_CHECKING

from wandb.proto import wandb_internal_pb2 as pb


if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run
    from wandb.sdk.interface.interface_shared import InterfaceShared


def get_random_intent_id(length: int = 12) -> str:
    # TODO(jhr): use secure hash?
    intent_id = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for i in range(length)
    )
    return intent_id


class Intent:
    _outcome: Optional[pb.IntentOutcome]

    def __init__(self, run: "Run", interface: "InterfaceShared") -> None:
        self._interface = interface
        self._proposed = False
        proto_run = self._interface._make_run(run)
        self._intent_id = get_random_intent_id()
        self._intent_request = pb.ProposeIntentRequest()
        self._intent_request.intent.run.CopyFrom(proto_run)
        self._intent_request.intent_id = self._intent_id
        self._outcome = None

    def propose(self) -> None:
        if self._proposed:
            return
        self._interface._propose_intent(self._intent_request)
        self._proposed = True

    def wait(
        self,
        timeout: Optional[int] = None,
        on_progress: Callable[[], None] = None,
        on_timeout: Callable[[], None] = None,
    ) -> None:
        self.propose()
        done = False
        inspect_request = pb.InspectIntentRequest(intent_id=self._intent_id)
        while not done:
            response = self._interface._inspect_intent(inspect_request)
            assert response  # TODO: is this right?
            if response.outcome.is_resolved:
                self._outcome = response.outcome
                done = True
                continue
            if on_progress:
                on_progress()
            time.sleep(1)

    @property
    def resolved(self) -> Optional[pb.IntentOutcome]:
        assert self._outcome
        return self._outcome

    @property
    def is_resolved(self) -> bool:
        return self._outcome is not None


def create_run(run: "Run", interface: "InterfaceShared") -> Intent:
    intent = Intent(run=run, interface=interface)
    return intent
