from __future__ import annotations

import dspy
import wandb


class MinimalProgram(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.predict = dspy.Predict("question: str -> answer: str")


def main() -> None:
    from wandb.integration.dspy import WandbDSPyCallback

    with wandb.init(project="dspy-system-test-unexpected") as run:
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

        # Pass an unexpected outputs type (not EvaluationResult)
        class NotAnEvaluationResult:
            pass

        cb.on_evaluate_end(
            call_id="c1", outputs=NotAnEvaluationResult(), exception=None
        )


if __name__ == "__main__":
    main()
