import pathlib
import sys

import dspy
import wandb
from dspy.evaluate.evaluate import EvaluationResult  # type: ignore


class MinimalProgram(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.predict = dspy.Predict("question: str -> answer: str")


def _results(score_value: float):
    ex = dspy.Example(question="What is 2+2?", answer="4")
    pred = dspy.Prediction(answer="4")
    results = [(ex, pred, True)]
    return EvaluationResult(score=score_value, results=results)


def main() -> None:
    from wandb.integration.dspy import WandbDSPyCallback

    # Ensure we import local repo 'wandb' package (not site-packages)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

    wandb_run = wandb.init(project="dspy-system-test-steps")
    cb = WandbDSPyCallback(log_results=True, wandb_run=wandb_run)

    class FakeEvaluate:
        def __init__(self) -> None:
            self.devset = []
            self.num_threads = 1
            self.auto = "light"

    program = MinimalProgram()
    cb.on_evaluate_start(
        call_id="c1", instance=FakeEvaluate(), inputs={"program": program}
    )

    # First step
    cb.on_evaluate_end(call_id="c1", outputs=_results(0.8), exception=None)
    # Second step
    cb.on_evaluate_end(call_id="c1", outputs=_results(0.9), exception=None)

    wandb.finish()


if __name__ == "__main__":
    main()
