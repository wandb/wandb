from __future__ import annotations

import pytest
import wandb
from wandb import util
from wandb.errors import term


def test_no_dynamic_text_if_silent(emulated_terminal):
    # Set up as if stderr is a terminal.
    _ = emulated_terminal

    wandb.termsetup(wandb.Settings(silent=True), None)

    with term.dynamic_text() as text:
        assert text is None


def test_no_dynamic_text_if_not_tty(emulated_terminal, monkeypatch):
    # Set up as if stderr is a terminal.
    _ = emulated_terminal

    monkeypatch.setattr(term, "_sys_stderr_isatty", lambda: False)

    with term.dynamic_text() as text:
        assert text is None


def test_no_dynamic_text_if_dumb_term(emulated_terminal, monkeypatch):
    # Set up as if stderr is a terminal.
    _ = emulated_terminal

    monkeypatch.setenv("TERM", "dumb")

    with term.dynamic_text() as text:
        assert text is None


def test_dynamic_text_prints(emulated_terminal):
    with term.dynamic_text() as text:
        assert text
        emulated_terminal.reset_capsys()

        text.set_text("one\ntwo\nthree")

        assert emulated_terminal.read_stderr() == [
            "wandb: one",
            "wandb: two",
            "wandb: three",
        ]


def test_dynamic_text_clears_at_end(emulated_terminal):
    with term.dynamic_text() as text:
        assert text
        emulated_terminal.reset_capsys()

        text.set_text("one\ntwo\nthree")

    assert emulated_terminal.read_stderr() == []


def test_dynamic_text_multiple(emulated_terminal):
    with term.dynamic_text() as text1:
        assert text1
        with term.dynamic_text() as text2:
            assert text2
            emulated_terminal.reset_capsys()

            text1.set_text("one\ntwo\nthree")
            text2.set_text("four\nfive")
            text1.set_text("updated")

            assert emulated_terminal.read_stderr() == [
                "wandb: updated",
                "wandb: four",
                "wandb: five",
            ]
        assert emulated_terminal.read_stderr() == ["wandb: updated"]


def test_static_and_dynamic_text(emulated_terminal):
    with term.dynamic_text() as text:
        assert text
        emulated_terminal.reset_capsys()

        text.set_text("my\nanimated\ntext")
        wandb.termlog("static text above animated text")
        wandb.termlog("static text #2")
        text.set_text("my\nanimated, updated\ntext")

        assert emulated_terminal.read_stderr() == [
            "wandb: static text above animated text",
            "wandb: static text #2",
            "wandb: my",
            "wandb: animated, updated",
            "wandb: text",
        ]


def test_truncates_dynamic_text(emulated_terminal, monkeypatch):
    # Pretend the terminal is very narrow.
    columns = len("wandb: this should fit")
    monkeypatch.setattr(term, "_shutil_get_terminal_width", lambda: columns)
    with term.dynamic_text() as text:
        assert text
        emulated_terminal.reset_capsys()

        text.set_text("this should fit")
        assert emulated_terminal.read_stderr() == ["wandb: this should fit"]
        text.set_text("but not this line")
        assert emulated_terminal.read_stderr() == ["wandb: but not this..."]


@pytest.fixture
def terminput_valid_env(monkeypatch: pytest.MonkeyPatch):
    """Patch attributes that can_use_terminput checks to make it return True."""
    monkeypatch.setattr(term, "_silent", False)
    monkeypatch.setattr(term, "_show_info", True)
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(util, "_is_databricks", lambda: False)
    monkeypatch.setattr(term, "_in_jupyter", lambda: False)
    monkeypatch.setattr(term, "_sys_stderr_isatty", lambda: True)
    monkeypatch.setattr(term, "_sys_stdin_isatty", lambda: True)


@pytest.mark.usefixtures("terminput_valid_env")
def test_can_use_terminput():
    assert term.can_use_terminput()


@pytest.mark.usefixtures("terminput_valid_env")
def test_can_use_terminput_databricks(
    monkeypatch: pytest.MonkeyPatch,
):
    # Test for the check added for WB-5264.
    monkeypatch.setattr(util, "_is_databricks", lambda: True)

    assert not term.can_use_terminput()


@pytest.mark.parametrize(
    "inputs, expected_result",
    (
        ([" y "], True),
        (["Y "], True),
        (["yes"], True),
        ([" n"], False),
        (["No "], False),
        ([" N"], False),
        (["", "yellow", "no"], False),
        (["no yes", "yes"], True),
    ),
)
def test_confirm(
    inputs: list[str],
    expected_result: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remaining_inputs = list(inputs)

    def mock_terminput(*args, **kwargs) -> str:
        return remaining_inputs.pop()

    monkeypatch.setattr(term, "_terminput", mock_terminput)

    assert term.confirm("What?") == expected_result
