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

    with term.dynamic_text() as text:
        assert text is None


def test_no_dynamic_text_if_not_tty(monkeypatch):
    monkeypatch.setattr(term, "_sys_stderr_isatty", lambda: False)

    with term.dynamic_text() as text:
        assert text is None


def test_no_dynamic_text_if_dumb_term(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")

    with term.dynamic_text() as text:
        assert text is None


def test_dynamic_text(capsys):
    with term.dynamic_text() as text1:
        assert text1

        with term.dynamic_text() as text2:
            assert text2

            text1.set_text("one\ntwo\nthree")
            text2.set_text("four\nfive")
            text1.set_text("updated")

    captured = capsys.readouterr()
    assert captured.err.split("\n") == [
        # text1.set_text()
        f"{BLUE_WANDB}: one",
        f"{BLUE_WANDB}: two",
        f"{BLUE_WANDB}: three",
        # text2.set_text()
        (3 * ANSI_DEL_LINE) + f"{BLUE_WANDB}: one",
        f"{BLUE_WANDB}: two",
        f"{BLUE_WANDB}: three",
        f"{BLUE_WANDB}: four",
        f"{BLUE_WANDB}: five",
        # text1.set_text()
        (5 * ANSI_DEL_LINE) + f"{BLUE_WANDB}: updated",
        f"{BLUE_WANDB}: four",
        f"{BLUE_WANDB}: five",
        # <end of text2>
        (3 * ANSI_DEL_LINE) + f"{BLUE_WANDB}: updated",
        # <end of text1>
        (1 * ANSI_DEL_LINE),
    ]


def test_static_and_dynamic_text(capsys):
    with term.dynamic_text() as text:
        assert text

        text.set_text("my\nanimated\ntext")
        wandb.termlog("static text above animated text")

    captured = capsys.readouterr()
    assert captured.err.split("\n") == [
        f"{BLUE_WANDB}: my",
        f"{BLUE_WANDB}: animated",
        f"{BLUE_WANDB}: text",
        (3 * ANSI_DEL_LINE) + f"{BLUE_WANDB}: static text above animated text",
        f"{BLUE_WANDB}: my",
        f"{BLUE_WANDB}: animated",
        f"{BLUE_WANDB}: text",
        (3 * ANSI_DEL_LINE),
    ]
