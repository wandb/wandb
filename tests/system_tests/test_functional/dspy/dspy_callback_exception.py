from __future__ import annotations

import dspy
import wandb
from dspy.evaluate.evaluate import EvaluationResult  # type: ignore


class MinimalProgram(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.predict = dspy.Predict("question: str -> answer: str")


def _build_results_stub():
    ex1 = dspy.Example(question="What is 5-2?", answer="3")
    pred1 = dspy.Prediction(answer="3")
    return [(ex1, pred1, True)]


def main() -> None:
    from wandb.integration.dspy import WandbDSPyCallback

    with wandb.init(project="dspy-system-test-exception") as run:
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
        out = EvaluationResult(score=0.1, results=results)

        # Simulate an exception during evaluation end
        cb.on_evaluate_end(call_id="c1", outputs=out, exception=Exception("boom"))


if __name__ == "__main__":
    main()
