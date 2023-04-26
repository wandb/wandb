import pytest
from wandb.sdk.lib.printer import PrinterTerm


@pytest.mark.parametrize("level", [1.3, {}, []])
def test_printer_invalid_level_type(level):
    printer = PrinterTerm()
    with pytest.raises(ValueError, match="Unknown status level"):
        printer.display("test string", level=level)
