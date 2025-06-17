from typing import Iterator

import pytest
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.lib import printer as p
from wandb.sdk.lib import progress


@pytest.fixture()
def dynamic_progress_printer(
    emulated_terminal,
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


def test_minimal_operations_dynamic(emulated_terminal, dynamic_progress_printer):
    dynamic_progress_printer.update(
        [
            pb.PollExitResponse(
                operation_stats=pb.OperationStats(
                    total_operations=4,
                    operations=[
                        pb.Operation(desc="op 1", runtime_seconds=45.315),
                        pb.Operation(desc="op 2", runtime_seconds=9.123),
                        pb.Operation(desc="op 3", runtime_seconds=123.45),
                        pb.Operation(desc="op 4", runtime_seconds=5000),
                    ],
                ),
            )
        ]
    )

    assert emulated_terminal.read_stderr() == [
        "wandb: ⢿ op 1 (45s)",
        "wandb: ⢿ op 2 (9.1s)",
        "wandb: ⢿ op 3 (2.1m)",
        "wandb: ⢿ op 4 (1h23m)",
    ]


def test_minimal_operations_static(mock_wandb_log, static_progress_printer):
    static_progress_printer.update(
        [
            pb.PollExitResponse(
                operation_stats=pb.OperationStats(
                    total_operations=4,
                    operations=[
                        pb.Operation(desc=f"op {i}", runtime_seconds=45.315)
                        for i in range(1, 101)
                    ],
                ),
            )
        ]
    )

    assert mock_wandb_log.logged("op 1; op 2; op 3; op 4; op 5 (+ 95 more)")


def test_operation_progress_and_error(
    emulated_terminal,
    dynamic_progress_printer,
):
    dynamic_progress_printer.update(
        [
            pb.PollExitResponse(
                operation_stats=pb.OperationStats(
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
        ]
    )

    assert emulated_terminal.read_stderr() == [
        "wandb: ⢿ op 1 4/9 (45s)",
        "wandb:   ERROR retrying HTTP 419",
    ]


def test_operation_subtasks(emulated_terminal, dynamic_progress_printer):
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
        [
            pb.PollExitResponse(
                operation_stats=pb.OperationStats(
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
        ]
    )

    assert emulated_terminal.read_stderr() == [
        "wandb: ⢿ op 1 (45s)",
        "wandb:   ↳ ⢿ subtask 4MB/9MB (1.2s)",
        "wandb:       ERROR retrying HTTP 419",
        "wandb:     ↳ ⢿ subsubtask 1/2 (5.0s)",
        "wandb:         ERROR not connected to internet",
    ]


def test_remaining_operations(emulated_terminal, dynamic_progress_printer):
    dynamic_progress_printer.update(
        [
            pb.PollExitResponse(
                operation_stats=pb.OperationStats(
                    total_operations=20,
                    operations=[
                        pb.Operation(desc="op 1"),
                    ],
                ),
            )
        ]
    )

    assert emulated_terminal.read_stderr() == [
        "wandb: ⢿ op 1 (0.0s)",
        "wandb: + 19 more task(s)",
    ]


def test_no_operations_text(emulated_terminal, dynamic_progress_printer):
    dynamic_progress_printer.update([pb.PollExitResponse()])

    assert emulated_terminal.read_stderr() == ["wandb: ⢿ DEFAULT TEXT"]
