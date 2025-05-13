from __future__ import annotations

import contextlib
from typing import Any, Iterator

import pytest
import wandb
from wandb.sdk.lib import printer, printer_asyncio
from wandb.sdk.lib.printer import _PrinterTerm


class MockDynamicTextPrinter(_PrinterTerm):
    """Test printer that captures text set through dynamic text."""

    def __init__(self) -> None:
        super().__init__(settings=wandb.Settings())
        self._captured_text: list[str] = []

    @property
    def captured_text(self) -> list[str]:
        return self._captured_text

    @contextlib.contextmanager
    def dynamic_text(self) -> Iterator[printer.DynamicText | None]:
        class TestDynamicText(printer.DynamicText):
            def __init__(self, printer: MockDynamicTextPrinter) -> None:
                self._printer = printer

            def set_text(self, text: str) -> None:
                self._printer._captured_text.append(text)

        yield TestDynamicText(self)


def test_run_async_with_spinner():
    test_printer = MockDynamicTextPrinter()

    def slow_func() -> int:
        return 42

    result = printer_asyncio.run_async_with_spinner(
        test_printer,
        "Loading",
        slow_func,
    )

    assert result == 42
    assert len(test_printer.captured_text) > 0
    assert all("Loading" in text for text in test_printer.captured_text)


def test_run_async_with_spinner_exception():
    test_printer = MockDynamicTextPrinter()

    def failing_func() -> Any:
        raise ValueError("Test error")

    with pytest.raises(ValueError, match="Test error"):
        printer_asyncio.run_async_with_spinner(
            test_printer,
            "Loading",
            failing_func,
        )

    assert len(test_printer.captured_text) > 0
    assert all("Loading" in text for text in test_printer.captured_text)
