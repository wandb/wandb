import dspy
import wandb
from dspy.evaluate.evaluate import EvaluationResult  # type: ignore


class MinimalProgram(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.predict = dspy.Predict("question: str -> answer: str")


def main() -> None:
    from wandb.integration.dspy import WandbDSPyCallback

    with wandb.init(project="dspy-system-test-noprogram") as run:
        cb = WandbDSPyCallback(log_results=True, run=run)

        class FakeEvaluate:
            def __init__(self) -> None:
                self.devset = []
                self.num_threads = 1
                self.auto = "light"

        # Start without a program
        cb.on_evaluate_start(call_id="c1", instance=FakeEvaluate(), inputs={})

        # Still emit a valid result and ensure program_signature is logged with minimal columns
        ex1 = dspy.Example(question="What is 7+1?", answer="8")
        pred1 = dspy.Prediction(answer="8")
        out = EvaluationResult(score=0.8, results=[(ex1, pred1, True)])
        cb.on_evaluate_end(call_id="c1", outputs=out, exception=None)


if __name__ == "__main__":
    main()
