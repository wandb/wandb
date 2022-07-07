from wandb.sdk.lib.printer import PrinterTerm
import pytest


@pytest.mark.parametrize("level", [1.3, {}, []])
def test_printer_invalid_level_type(level):
    printer = PrinterTerm()
    with pytest.raises(ValueError, match="Unknown status level"):
        printer.display("test string", level=level)


@pytest.mark.parametrize("level", ["random", ""])
def test_printer_invalid_level_str(level):
    printer = PrinterTerm()
    with pytest.raises(ValueError, match="Unknown level name"):
        printer.display("test string", level=level)


@pytest.mark.parametrize(
    "level, prefix",
    [
        (55, "wandb: ERROR"),
        (12, "wandb:"),
        (0, "wandb:"),
    ],
)
def test_printer_levels(level, prefix, capsys):
    printer = PrinterTerm()
    printer.display("test string", level=level)
    outerr = capsys.readouterr()
    assert outerr.out == ""
    assert outerr.err == f"{prefix} test string\n"
