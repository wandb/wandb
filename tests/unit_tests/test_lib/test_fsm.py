from __future__ import annotations

from wandb.sdk.lib.fsm import Fsm, FsmEntry

# TODO(testing): investigate if we can use unittest.mock and Call() tracking


class TrackCalls:
    def __init__(self, calls):
        self._calls = calls


class A(TrackCalls):
    def __init__(self, calls):
        super().__init__(calls)

    def on_state(self, inputs) -> None:
        self._calls.append("A:on_state")

    def to_b(self, inputs) -> bool:
        self._calls.append("to_b")
        return True


class B(TrackCalls):
    def __init__(self, calls):
        super().__init__(calls)

    def on_state(self, inputs) -> None:
        self._calls.append("B:on_state")

    def to_a(self, inputs) -> bool:
        self._calls.append("to_a")
        return True


def test_normal():
    calls = []
    sa = A(calls)
    sb = B(calls)
    f = Fsm(
        states=(sa, sb), table={A: [FsmEntry(sa.to_b, B)], B: [FsmEntry(sb.to_a, A)]}
    )

    f.input({"input1": 1, "input2": 2})
    assert calls == ["to_b", "B:on_state"]
