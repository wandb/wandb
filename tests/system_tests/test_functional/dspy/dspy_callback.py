import dspy
import wandb
from dspy.evaluate.evaluate import EvaluationResult  # type: ignore


class MinimalProgram(dspy.Module):
    """Minimal DSPy module exposing a `Predict` param for signature extraction.

    Examples:
        >>> mod = MinimalProgram()
    """

    def __init__(self) -> None:
        super().__init__()
        self.predict = dspy.Predict("question: str -> answer: str")


def _build_results_stub():
    """Construct a small set of results for `_log_predictions_table`.

    Returns:
        list: A list of tuples `(example, prediction, is_correct)`.

    Examples:
        >>> rows = _build_results_stub()
        >>> len(rows) >= 1
        True
    """
    ex1 = dspy.Example(question="What is 2+2?", answer="4")
    pred1 = dspy.Prediction(answer="4")

    ex2 = dspy.Example(question="What is 3+3?", answer="6")
    pred2 = dspy.Prediction(answer="6")

    return [
        (ex1, pred1, True),
        (ex2, pred2, True),
    ]


def main() -> None:
    """Run a minimal end-to-end example invoking `WandbDSPyCallback`.

    The flow:
    - Install a fake `dspy` to avoid external dependencies.
    - Initialize a W&B run.
    - Instantiate and exercise the callback by simulating evaluate start/end.
    - Log a model via `log_best_model` in multiple modes.

    Examples:
        >>> if __name__ == "__main__":
        ...     main()
    """
    from wandb.integration.dspy import WandbDSPyCallback

    # Init W&B
    with wandb.init(project="dspy-system-test") as run:
        # Build callback
        cb = WandbDSPyCallback(log_results=True, run=run)

        # Simulate dspy.Evaluate instance and lifecycle
        class FakeEvaluate:
            def __init__(self) -> None:
                self.devset = [1, 2, 3]  # should be excluded from config
                self.num_threads = 2
                self.auto = "light"

        program = MinimalProgram()
        cb.on_evaluate_start(
            call_id="c1", instance=FakeEvaluate(), inputs={"program": program}
        )

        # Emit an evaluation result with prediction rows
        results = _build_results_stub()
        out = EvaluationResult(score=0.8, results=results)
        cb.on_evaluate_end(call_id="c1", outputs=out, exception=None)

        # Exercise model artifact saving in different modes using the real Module API
        cb.log_best_model(program, save_program=True)
        cb.log_best_model(program, save_program=False, filetype="json")
        cb.log_best_model(program, save_program=False, filetype="pkl")


if __name__ == "__main__":
    main()
