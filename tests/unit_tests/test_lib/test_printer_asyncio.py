from __future__ import annotations

import contextlib
import threading
from typing import Iterator
from unittest.mock import Mock

import pytest
from wandb.sdk.lib import printer, printer_asyncio


class _Tester:
    """Helper to test run_async_with_spinner."""

    def __init__(self, loading_symbol: str) -> None:
        self._printed = threading.Event()

        def mark_printed(*_) -> None:
            self._printed.set()

        self._mock_dynamic_text = Mock(spec=printer.DynamicText)
        self._mock_dynamic_text.set_text.side_effect = mark_printed

        self._mock_printer = Mock(spec=printer.Printer)
        self._mock_printer.dynamic_text.side_effect = self._dynamic_text
        self._mock_printer.loading_symbol.return_value = loading_symbol

    @contextlib.contextmanager
    def _dynamic_text(self) -> Iterator[printer.DynamicText]:
        """Fake implementation of Printer.dynamic_text."""
        yield self._mock_dynamic_text

    @property
    def printer(self) -> printer.Printer:
        """The mock printer to use in the test."""
        return self._mock_printer

    @property
    def mock_set_text(self) -> Mock:
        """The mock set_text() on the DynamicText object."""
        return self._mock_dynamic_text.set_text

    def wait_until_set_text(self) -> None:
        """Block until set_text() is called at least once.

        Necessary since the function passed to `run_async_with_spinner` races
        with the code that prints the text.
        """
        if not self._printed.wait(timeout=1):
            raise TimeoutError


def test_run_async_with_spinner():
    tester = _Tester(loading_symbol="***")

    def slow_func() -> int:
        tester.wait_until_set_text()
        return 42

    result = printer_asyncio.run_async_with_spinner(
        tester.printer,
        "Loading",
        slow_func,
    )

    assert result == 42
    tester.mock_set_text.assert_called_with("*** Loading")


def test_run_async_with_spinner_exception():
    tester = _Tester(loading_symbol="***")

    def failing_func() -> None:
        tester.wait_until_set_text()
        raise ValueError("Test error")

    with pytest.raises(ValueError, match="Test error"):
        printer_asyncio.run_async_with_spinner(
            tester.printer,
            "Loading",
            failing_func,
        )

    tester.mock_set_text.assert_called_with("*** Loading")
