"""Unit tests of the sweep scheduler's controller run logger.

No console capture is installed here: these exercise the line assembly
and the labeling that the capture callbacks feed into.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from wandb.sdk.sweeps.scheduler.run_logger import (
    _MAX_HELD_CHARACTERS,
    ControllerRunLogger,
    LineBuffer,
)


def published_lines(run: MagicMock) -> list[tuple[str, str, bool]]:
    """The (line, label, is_error) of each line appended to the run."""
    return [
        (call.args[0], call.kwargs["label"], call.kwargs["is_error"])
        for call in run._interface.publish_run_log.call_args_list
    ]


class TestLineBuffer:
    def test_returns_only_finished_lines(self):
        buffer = LineBuffer()

        assert buffer.take_lines("first\nsecond\npart") == ["first", "second"]

    def test_joins_a_line_split_across_writes(self):
        buffer = LineBuffer()

        assert buffer.take_lines("half ") == []
        assert buffer.take_lines("a line\n") == ["half a line"]

    def test_strips_carriage_returns(self):
        buffer = LineBuffer()

        assert buffer.take_lines("windows\r\n") == ["windows"]

    def test_flushes_a_partial_line_that_grows_too_long(self):
        buffer = LineBuffer()
        redrawn = "x" * _MAX_HELD_CHARACTERS

        assert buffer.take_lines(redrawn) == [redrawn]
        # Having been flushed, it is not repeated by the next line.
        assert buffer.take_lines("\n") == [""]

    def test_take_rest_returns_the_held_line(self):
        buffer = LineBuffer()
        buffer.take_lines("no newline")

        assert buffer.take_rest() == ["no newline"]
        assert buffer.take_rest() == []

    def test_take_rest_holding_nothing(self):
        assert LineBuffer().take_rest() == []


class TestControllerRunLogger:
    @pytest.fixture
    def run(self) -> MagicMock:
        return MagicMock()

    def test_captured_output_is_appended_a_line_at_a_time(self, run):
        logger = ControllerRunLogger(run)

        logger.write_stdout("first\nhalf ")
        logger.write_stderr("from the other stream\n")
        logger.write_stdout("a line\n")

        # Severity is not inferred from the stream: this process prints
        # even its informational messages to stderr.
        assert published_lines(run) == [
            ("first", "", False),
            ("from the other stream", "", False),
            ("half a line", "", False),
        ]

    def test_log_appends_under_the_given_label(self, run):
        logger = ControllerRunLogger(run)

        logger.log("generating 2 runs", label="optuna")

        assert published_lines(run) == [("generating 2 runs", "optuna", False)]

    def test_log_records_errors_as_errors(self, run):
        logger = ControllerRunLogger(run)

        logger.log("it broke", level=logging.ERROR)

        assert published_lines(run) == [("it broke", "", True)]

    def test_log_spells_out_a_warning(self, run):
        # term marks the severity on the terminal, but the run has no
        # level between info and error to carry it.
        logger = ControllerRunLogger(run)

        logger.log("model stalled", level=logging.WARNING)

        assert published_lines(run) == [("WARNING model stalled", "", False)]

    def test_close_appends_an_unfinished_line(self, run):
        logger = ControllerRunLogger(run)
        logger.write_stdout("no newline yet")

        logger.close()

        assert published_lines(run) == [("no newline yet", "", False)]

    def test_nothing_is_appended_after_close(self, run):
        logger = ControllerRunLogger(run)

        logger.close()
        logger.log("too late")

        assert published_lines(run) == []

    def test_close_is_idempotent(self, run):
        logger = ControllerRunLogger(run)
        logger.write_stdout("no newline yet")

        logger.close()
        logger.close()

        assert len(published_lines(run)) == 1

    def test_a_failed_append_costs_the_line_not_the_sweep(self, run):
        run._interface.publish_run_log.side_effect = Exception("queue closed")
        logger = ControllerRunLogger(run)

        logger.log("dropped")
