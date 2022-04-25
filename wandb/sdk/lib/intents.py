"""
intents.
"""

import secrets
import string
import time
from typing import Optional

from wandb.proto import wandb_internal_pb2 as pb


def get_random_intent_id(length: int = 12) -> str:
    intent_id = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for i in range(length)
    )
    return intent_id


class Intent:
    def __init__(self, run=None, interface=None):
        self._interface = interface
        self._submitted = False
        proto_run = self._interface._make_run(run)
        self._intent_id = get_random_intent_id()
        self._intent_request = pb.ProposeIntentRequest()
        self._intent_request.intent.run.CopyFrom(proto_run)
        self._intent_request.intent_id = self._intent_id
        self._outcome = None

    def propose(self):
        if self._submitted:
            return
        self._interface._propose_intent(self._intent_request)
        self._submitted = True

    def wait(self, timeout=None, on_progress=None, on_timeout=None):
        self.propose()
        done = False
        inspect_request = pb.InspectIntentRequest(intent_id=self._intent_id)
        while not done:
            response = self._interface._inspect_intent(inspect_request)
            if response.outcome.is_resolved:
                self._outcome = response.outcome
                done = True
                continue
            if on_progress:
                on_progress()
            time.sleep(1)

    def recall(self):
        pass

    @property
    def outcome(self) -> Optional[pb.IntentOutcome]:
        return self._outcome

    @property
    def is_resolved(self) -> bool:
        return True

    @property
    def is_cancelled(self) -> bool:
        return False
