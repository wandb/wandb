import dspy
import wandb
from dspy.evaluate.evaluate import EvaluationResult  # type: ignore


class MinimalProgram(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.predict = dspy.Predict("question: str -> answer: str")


class DummyCompletions:
    """Minimal stand-in for dspy.Completions to exercise .items() branch."""

    def __init__(self, data):
        self._data = data

    def items(self):
        return list(self._data.items())


def _build_results_stub():
    ex = dspy.Example(question="What is 10-3?", answer="7")
    # Ensure isinstance(pred, dspy.Completions) is True by monkeypatching
    dspy.Completions = DummyCompletions  # type: ignore[attr-defined]
    pred = dspy.Completions({"answer": "7"})  # type: ignore[call-arg]
    return [(ex, pred, True)]


def main() -> None:
    from wandb.integration.dspy import WandbDSPyCallback

    with wandb.init(project="dspy-system-test-completions") as run:
        cb = WandbDSPyCallback(log_results=True, run=run)

        class FakeEvaluate:
            def __init__(self) -> None:
                self.devset = []
                self.num_threads = 1
                self.auto = "light"

        program = MinimalProgram()
        cb.on_evaluate_start(
            call_id="c1", instance=FakeEvaluate(), inputs={"program": program}
        )

        results = _build_results_stub()
        out = EvaluationResult(score=0.8, results=results)
        cb.on_evaluate_end(call_id="c1", outputs=out, exception=None)


if __name__ == "__main__":
    main()
