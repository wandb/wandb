from wandb.sdk.lib import fsm
from wandb.sdk.lib.fsm import Fsm


def test_normal():
    class A:
        def run(self, inputs) -> None:
            pass

    class B:
        def run(self, inputs) -> None:
            pass

    def to_b(inputs) -> bool:
        return True

    def to_a(inputs) -> bool:
        return True

    f = Fsm(states=[A(), B()], table={A: [(to_b, B)], B: [(to_a, A)]})

    f.run({"input1": 1, "input2": 2})
