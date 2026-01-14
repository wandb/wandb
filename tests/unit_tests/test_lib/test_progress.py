from collections.abc import Iterator

import pytest
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.lib import printer as p
from wandb.sdk.lib import progress

from tests.fixtures.emulated_terminal import EmulatedTerminal
from tests.fixtures.mock_wandb_log import MockWandbLog


@pytest.fixture()
def dynamic_progress_printer(
    emulated_terminal: EmulatedTerminal,
) -> Iterator[progress.ProgressPrinter]:
    """A ProgressPrinter writing to an emulated terminal."""
    # Ensure dynamic text is supported.
    _ = emulated_terminal

    with progress.progress_printer(
        p.new_printer(),
        "DEFAULT TEXT",
    ) as progress_printer:
        yield progress_printer


@pytest.fixture()
def static_progress_printer() -> Iterator[progress.ProgressPrinter]:
    """A ProgressPrinter that writes to a file or dumb terminal."""
    with progress.progress_printer(
        p.new_printer(),
        "DEFAULT TEXT",
    ) as progress_printer:
        yield progress_printer


def test_minimal_operations_dynamic(
    emulated_terminal: EmulatedTerminal,
    dynamic_progress_printer: progress.ProgressPrinter,
):
    dynamic_progress_printer.update(
        pb.OperationStats(
            total_operations=4,
            operations=[
                pb.Operation(desc="op 1", runtime_seconds=45.315),
                pb.Operation(desc="op 2", runtime_seconds=9.123),
                pb.Operation(desc="op 3", runtime_seconds=123.45),
                pb.Operation(desc="op 4", runtime_seconds=5000),
            ],
        ),
    )

    assert emulated_terminal.read_stderr() == [
        "wandb: ⢿ op 1 (45s)",
        "wandb: ⢿ op 2 (9.1s)",
        "wandb: ⢿ op 3 (2.1m)",
        "wandb: ⢿ op 4 (1h23m)",
    ]


def test_grouped_operations_dynamic(
    emulated_terminal: EmulatedTerminal,
    dynamic_progress_printer: progress.ProgressPrinter,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(progress, "_MAX_LINES_TO_PRINT", 7)

    dynamic_progress_printer.update(
        [
            pb.OperationStats(
                label="run1",
                total_operations=100,
                operations=[
                    pb.Operation(desc="op 1", runtime_seconds=45.315),
                    pb.Operation(desc="op 2", runtime_seconds=9.123),
                ],
            ),
            pb.OperationStats(
                label="run2",
                total_operations=20,
                operations=[],  # no operations => group not printed
            ),
            pb.OperationStats(
                label="run3",
                total_operations=3,
                operations=[
                    pb.Operation(desc="op 3", runtime_seconds=5000),
                    # over line limit => not printed
                    pb.Operation(desc="op 4"),
                ],
            ),
        ]
    )

    assert emulated_terminal.read_stderr() == [
        "wandb: run1",
        "wandb:   ⢿ op 1 (45s)",
        "wandb:   ⢿ op 2 (9.1s)",
        "wandb:   + 98 more task(s)",
        "wandb: run3",
        "wandb:   ⢿ op 3 (1h23m)",
        "wandb:   + 2 more task(s)",
    ]


def test_grouped_operations_near_max_lines(
    emulated_terminal: EmulatedTerminal,
    dynamic_progress_printer: progress.ProgressPrinter,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(progress, "_MAX_LINES_TO_PRINT", 5)

    # The first run takes 4 lines, but the second run needs at least 2 lines,
    # so it is not printed.
    dynamic_progress_printer.update(
        [
            pb.OperationStats(
                label="run1",
                total_operations=100,
                operations=[
                    pb.Operation(desc="op 1", runtime_seconds=45.315),
                    pb.Operation(desc="op 2", runtime_seconds=9.123),
                ],
            ),
            pb.OperationStats(
                label="run2",
                total_operations=20,
                operations=[
                    pb.Operation(desc="op 3", runtime_seconds=5000),
                ],
            ),
        ]
    )

    assert emulated_terminal.read_stderr() == [
        "wandb: run1",
        "wandb:   ⢿ op 1 (45s)",
        "wandb:   ⢿ op 2 (9.1s)",
        "wandb:   + 98 more task(s)",
    ]


def test_minimal_operations_static(
    mock_wandb_log: MockWandbLog,
    static_progress_printer: progress.ProgressPrinter,
):
    static_progress_printer.update(
        pb.OperationStats(
            total_operations=200,
            operations=[
                pb.Operation(desc=f"op {i}", runtime_seconds=45.315)
                for i in range(1, 101)
            ],
        ),
    )

    mock_wandb_log.assert_logged("op 1; op 2; op 3; op 4; op 5 (+ 195 more)")


def test_grouped_operations_static(
    mock_wandb_log: MockWandbLog,
    static_progress_printer: progress.ProgressPrinter,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(progress, "_MAX_OPS_TO_PRINT", 3)

    static_progress_printer.update(
        [
            pb.OperationStats(
                label="run1",
                total_operations=100,
                operations=[pb.Operation(desc="op 1"), pb.Operation(desc="op 2")],
            ),
            pb.OperationStats(
                label="run2",
                total_operations=20,
                operations=[],  # no operations => group not printed
            ),
            pb.OperationStats(
                label="run3",
                total_operations=3,
                operations=[
                    pb.Operation(desc="op 3"),
                    pb.Operation(desc="op 4"),  # over limit => not printed
                ],
            ),
            pb.OperationStats(  # over limit => not printed
                label="run4",
                total_operations=1,
                operations=[pb.Operation(desc="op 5")],
            ),
        ]
    )

    mock_wandb_log.assert_logged("[run1] op 1; op 2; [run3] op 3 (+ 121 more)")


def test_does_not_print_empty_lines(
    capsys: pytest.CaptureFixture[str],
    static_progress_printer: progress.ProgressPrinter,
):
    stats1 = pb.OperationStats(
        total_operations=1,
        operations=[pb.Operation(desc="op 1", runtime_seconds=123)],
    )
    static_progress_printer.update(stats1)

    # Normally, this prints a new line whenever the status changes.
    # But since the new status is empty, it should just be ignored.
    static_progress_printer.update(pb.OperationStats(total_operations=0))
    # The new status is different from the previous one (empty),
    # but it's the same as the last *printed* one, so it should be skipped.
    static_progress_printer.update(stats1)

    assert capsys.readouterr().err.splitlines() == [
        "wandb: op 1",
    ]


def test_operation_progress_and_error(
    emulated_terminal: EmulatedTerminal,
    dynamic_progress_printer: progress.ProgressPrinter,
):
    dynamic_progress_printer.update(
        pb.OperationStats(
            total_operations=1,
            operations=[
                pb.Operation(
                    desc="op 1",
                    runtime_seconds=45.315,
                    progress="4/9",
                    error_status="retrying HTTP 419",
                ),
            ],
        ),
    )

    assert emulated_terminal.read_stderr() == [
        "wandb: ⢿ op 1 4/9 (45s)",
        "wandb:   ERROR retrying HTTP 419",
    ]


def test_operation_subtasks(
    emulated_terminal: EmulatedTerminal,
    dynamic_progress_printer: progress.ProgressPrinter,
):
    subsubtask = pb.Operation(
        desc="subsubtask",
        runtime_seconds=5,
        progress="1/2",
        error_status="not connected to internet",
    )
    subtask = pb.Operation(
        desc="subtask",
        runtime_seconds=1.22,
        progress="4MB/9MB",
        error_status="retrying HTTP 419",
        subtasks=[subsubtask],
    )

    dynamic_progress_printer.update(
        pb.OperationStats(
            total_operations=1,
            operations=[
                pb.Operation(
                    desc="op 1",
                    runtime_seconds=45.315,
                    subtasks=[subtask],
                ),
            ],
        ),
    )

    assert emulated_terminal.read_stderr() == [
        "wandb: ⢿ op 1 (45s)",
        "wandb:   ↳ ⢿ subtask 4MB/9MB (1.2s)",
        "wandb:       ERROR retrying HTTP 419",
        "wandb:     ↳ ⢿ subsubtask 1/2 (5.0s)",
        "wandb:         ERROR not connected to internet",
    ]


def test_remaining_operations(
    emulated_terminal: EmulatedTerminal,
    dynamic_progress_printer: progress.ProgressPrinter,
):
    dynamic_progress_printer.update(
        pb.OperationStats(
            total_operations=20,
            operations=[
                pb.Operation(desc="op 1"),
            ],
        ),
    )

    assert emulated_terminal.read_stderr() == [
        "wandb: ⢿ op 1 (0.0s)",
        "wandb: + 19 more task(s)",
    ]


def test_no_operations_text(
    emulated_terminal: EmulatedTerminal,
    dynamic_progress_printer: progress.ProgressPrinter,
):
    dynamic_progress_printer.update(pb.OperationStats())

    assert emulated_terminal.read_stderr() == ["wandb: ⢿ DEFAULT TEXT"]
