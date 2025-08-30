import pytest
import wandb
from wandb.sdk.lib import printer as p


@pytest.mark.parametrize("level", [1.3, {}, []])
def test_printer_invalid_level_type(level):
    printer = p.new_printer()

    with pytest.raises(ValueError, match="Unknown status level"):
        printer.display("test string", level=level)


@pytest.mark.parametrize("level", ["random", ""])
def test_printer_invalid_level_str(level):
    printer = p.new_printer()

    with pytest.raises(ValueError, match="Unknown level name"):
        printer.display("test string", level=level)


@pytest.mark.parametrize(
    "level, prefix",
    [
        (p.CRITICAL, "wandb: ERROR"),
        (p.DEBUG, "wandb:"),
        (p.NOTSET, "wandb:"),
    ],
)
def test_printer_levels(level, prefix, capsys):
    printer = p.new_printer()

    printer.display("test string", level=level)

    outerr = capsys.readouterr()
    assert outerr.out == ""
    assert outerr.err == f"{prefix} test string\n"


def test_printer_term_silent(capsys):
    printer = p._PrinterTerm(settings=wandb.Settings(silent=True))

    printer.display("something")
    printer.progress_update("update")
    printer.progress_close()
    with printer.dynamic_text() as text_area:
        assert text_area is None

    outerr = capsys.readouterr()
    assert not outerr.out
    assert not outerr.err
