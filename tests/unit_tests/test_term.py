import click
import pytest
import wandb
from wandb.errors import term

ANSI_DEL_LINE = "\r\x1b[Am\x1b[2K\r"
"""ANSI sequence to delete the previous line.

Copied directly from the code being tested. The only way to test
that this actually works is to try it in many terminals. It's also
useful to consult online references about these escape sequences.
"""

BLUE_WANDB = click.style("wandb", fg="blue", bold=True)


@pytest.fixture(autouse=True)
def reset_logger():
    """Resets the logger before each test."""
    wandb.termsetup(wandb.Settings(silent=False), None)
    term._dynamic_blocks = []


@pytest.fixture(autouse=True)
def allow_dynamic_text(monkeypatch):
    """Pretends stderr is a TTY in each test by default."""
    monkeypatch.setenv("TERM", "xterm")

    monkeypatch.setattr(term, "_sys_stderr_isatty", lambda: True)

    # Make click pretend we're a TTY, so it doesn't strip ANSI sequences.
    # This is fragile and could break when click is updated.
    monkeypatch.setattr("click._compat.isatty", lambda *args, **kwargs: True)


def test_no_dynamic_text_if_silent():
    wandb.termsetup(wandb.Settings(silent=True), None)

    assert term.dynamic_text() is None


def test_no_dynamic_text_if_not_tty(monkeypatch):
    monkeypatch.setattr(term, "_sys_stderr_isatty", lambda: False)

    assert term.dynamic_text() is None


def test_no_dynamic_text_if_dumb_term(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")

    assert term.dynamic_text() is None


def test_dynamic_text(capsys):
    text1 = term.dynamic_text()
    text2 = term.dynamic_text()
    assert text1 and text2

    text1.set_text("one\ntwo\nthree")
    text2.set_text("four\nfive")
    text1.set_text("updated")
    text1.remove()

    captured = capsys.readouterr()
    assert (
        captured.err
        == (
            # text1.set_text()
            f"{BLUE_WANDB}: one\n"
            f"{BLUE_WANDB}: two\n"
            f"{BLUE_WANDB}: three\n"
            # text2.set_text()
            + (3 * ANSI_DEL_LINE)
            + f"{BLUE_WANDB}: one\n"
            f"{BLUE_WANDB}: two\n"
            f"{BLUE_WANDB}: three\n"
            f"{BLUE_WANDB}: four\n"
            f"{BLUE_WANDB}: five\n"
            # text1.set_text()
            + (5 * ANSI_DEL_LINE)  #
            + f"{BLUE_WANDB}: updated\n"
            f"{BLUE_WANDB}: four\n"
            f"{BLUE_WANDB}: five\n"
            # text1.remove()
            + (3 * ANSI_DEL_LINE)  #
            + f"{BLUE_WANDB}: four\n"
            f"{BLUE_WANDB}: five\n"
        )
    )
