from wandb.sdk.lib.fsm import Fsm, FsmEntry


def test_normal():
    class A:
        def on_state(self, inputs) -> None:
            pass

    class B:
        def on_state(self, inputs) -> None:
            pass

    def to_b(inputs) -> bool:
        return True

    def to_a(inputs) -> bool:
        return True

    f = Fsm(states=[A(), B()], table={A: [FsmEntry(to_b, B)], B: [FsmEntry(to_a, A)]})

    f.input({"input1": 1, "input2": 2})
