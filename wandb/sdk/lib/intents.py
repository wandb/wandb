"""
intents.
"""

import secrets
import string
from typing import Callable, Optional
from typing import TYPE_CHECKING

from wandb.proto import wandb_internal_pb2 as pb

from .mailbox import Mailbox


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
    _mailbox: Mailbox

    def __init__(self, run: "Run", interface: "InterfaceShared") -> None:
        self._interface = interface
        assert interface._mailbox
        self._mailbox = interface._mailbox
        self._proposed = False

        proto_run = self._interface._make_run(run)
        self._intent_id = get_random_intent_id()
        self._intent_request = pb.IntentPropose()
        self._intent_request.mailbox = self._mailbox.allocate_box()
        self._intent_request.intent.run.CopyFrom(proto_run)
        self._intent_request.intent_id = self._intent_id
        self._outcome = None

    def propose(self) -> None:
        if self._proposed:
            return
        self._interface._intent_propose(self._intent_request)
        self._proposed = True

    def wait(
        self,
        timeout: Optional[int] = None,
        on_progress: Callable[[], None] = None,
    ) -> None:
        self.propose()
        done = False
        # inspect_request = pb.IntentInspect(intent_id=self._intent_id)
        while not done:
            # response = self._interface._intent_inspect(inspect_request)
            # assert response  # TODO: is this right?
            # if response.outcome.is_resolved:
            #     self._outcome = response.outcome
            #     done = True
            #     continue
            mailbox = self._intent_request.mailbox
            found = self._mailbox.wait_box(mailbox, timeout=1)
            if found:
                self._outcome = found.response.intent_update.outcome
                done = True
                continue
            if on_progress:
                on_progress()

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
