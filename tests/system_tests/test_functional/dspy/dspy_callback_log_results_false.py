import sys
import pathlib
import dspy
import wandb
from dspy.evaluate.evaluate import EvaluationResult  # type: ignore


class MinimalProgram(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.predict = dspy.Predict("question: str -> answer: str")


def _build_results_stub():
    ex1 = dspy.Example(question="What is 1+1?", answer="2")
    pred1 = dspy.Prediction(answer="2")
    return [(ex1, pred1, True)]


def main() -> None:
    from wandb.integration.dspy import WandbDSPyCallback

    # Ensure we import local repo 'wandb' package (not site-packages)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

    wandb_run = wandb.init(project="dspy-system-test-nolog")

    cb = WandbDSPyCallback(log_results=False, wandb_run=wandb_run)

    class FakeEvaluate:
        def __init__(self) -> None:
            self.devset = []
            self.num_threads = 1
            self.auto = "light"

    program = MinimalProgram()
    cb.on_evaluate_start(call_id="c1", instance=FakeEvaluate(), inputs={"program": program})

    results = _build_results_stub()
    out = EvaluationResult(score=0.8, results=results)
    cb.on_evaluate_end(call_id="c1", outputs=out, exception=None)

    wandb.finish()


if __name__ == "__main__":
    main()


