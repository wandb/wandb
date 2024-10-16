import wandb
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

        text.set_text("one\ntwo\nthree")

        assert emulated_terminal.read_stderr() == [
            "wandb: one",
            "wandb: two",
            "wandb: three",
        ]


def test_dynamic_text_clears_at_end(emulated_terminal):
    with term.dynamic_text() as text:
        assert text
        text.set_text("one\ntwo\nthree")

    assert emulated_terminal.read_stderr() == []


def test_dynamic_text_multiple(emulated_terminal):
    with term.dynamic_text() as text1:
        assert text1
        with term.dynamic_text() as text2:
            assert text2

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
