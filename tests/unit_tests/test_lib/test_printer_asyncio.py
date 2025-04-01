import contextlib
import time
from typing import Any, Iterator, List
from unittest.mock import patch

import pytest
from wandb.sdk.lib import printer, printer_asyncio
from wandb.sdk.lib.printer import _PrinterTerm


class PrinterWrapper(_PrinterTerm):
    """A test printer that captures text set with set_text."""

    def __init__(self) -> None:
        super().__init__()
        self._captured_text: List[str] = []

    @property
    def captured_text(self) -> List[str]:
        return self._captured_text

    @contextlib.contextmanager
    def dynamic_text(self) -> Iterator[printer.DynamicText | None]:
        class TestDynamicText(printer.DynamicText):
            def __init__(self, printer: PrinterWrapper) -> None:
                self._printer = printer

            def set_text(self, text: str) -> None:
                self._printer._captured_text.append(text)

        yield TestDynamicText(self)


def test_run_async_with_spinner():
    test_printer = PrinterWrapper()

    with patch.object(printer, "new_printer", return_value=test_printer):

        def slow_func() -> int:
            time.sleep(0.5)
            return 42

        result = printer_asyncio.run_async_with_spinner("Loading", slow_func)
        assert result == 42
        assert len(test_printer.captured_text) > 0
        assert all("Loading" in text for text in test_printer.captured_text)


def test_run_async_with_spinner_exception():
    test_printer = PrinterWrapper()

    with patch.object(printer, "new_printer", return_value=test_printer):

        def failing_func() -> Any:
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            printer_asyncio.run_async_with_spinner("Loading", failing_func)
        assert len(test_printer.captured_text) > 0
        assert all("Loading" in text for text in test_printer.captured_text)
