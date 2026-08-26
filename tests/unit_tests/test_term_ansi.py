from wandb.errors.ansi import wrap_ansi


def test_wrap_ansi__wraps_printable_text():
    text = "0123456789abcdefghij"

    assert list(wrap_ansi(text, width=10, max_lines=2)) == [
        "0123456789",
        "abcdefghij",
    ]
    assert list(wrap_ansi(text + "x", width=10, max_lines=2)) == [
        "0123456789",
        "abcdefg...",
    ]


def test_wrap_ansi__includes_all_ansi():
    # The style reset sequence must be included even when the text inside
    # is truncated, or else the style will apply to later printed text.
    text = "\x1b[31mthis text is red \x1b[34mand this is blue\x1b[0m"

    result = list(wrap_ansi(text, width=10, max_lines=1))

    assert result == ["\x1b[31mthis te...\x1b[34m\x1b[0m"]


def test_wrap_ansi__exact_with_ansi_at_end():
    # Exactly 10 printable characters.
    #               0123456789
    text = "\x1b[31m10 are red\x1b[0m"

    result = list(wrap_ansi(text, width=10, max_lines=1))

    assert result == ["\x1b[31m10 are red\x1b[0m"]


def test_wrap_ansi__slightly_over_with_ansi_at_end():
    # Exactly 11 printable characters.
    #               0123456789       A
    text = "\x1b[31m11 are red\x1b[0m!"

    result = list(wrap_ansi(text, width=10, max_lines=1))

    assert result == ["\x1b[31m11 are ...\x1b[0m"]


def test_wrap_ansi__ellipsis_styling():
    # Exactly 12 printable characters.
    #               0123456               789AB
    # "not red" in red, then " text" in blue
    text = "\x1b[31mnot red\x1b[34m text\x1b[0m"

    result = list(wrap_ansi(text, width=10, max_lines=1))

    # The ellipsis is styled blue because the first character
    # it replaces is blue. It would be fine to make it red as well;
    # this just happens to be simpler to implement.
    assert result == ["\x1b[31mnot red\x1b[34m...\x1b[0m"]


def test_wrap_ansi__just_ansi():
    text = "\x1b[0m"

    result = list(wrap_ansi(text, width=10, max_lines=1))

    assert result == ["\x1b[0m"]


def test_wrap_ansi__short_width():
    text = "\x1b[31mred text\x1b[0m"

    result = list(wrap_ansi(text, width=1, max_lines=2))

    # The lines should not have more than 1 printable character in this
    # extreme case. The choice for the ellipsis character is not important.
    assert result == [
        "\x1b[31mr",
        ".\x1b[0m",
    ]


def test_wrap_ansi__no_width():
    result = list(wrap_ansi("\x1b[0msome text", width=0, max_lines=10))

    assert result == ["\x1b[0m"]


def test_wrap_ansi__empty_text():
    result = list(wrap_ansi("", width=10, max_lines=1))

    assert result == [""]


def test_wrap_ansi__zero_max_lines():
    result = list(wrap_ansi("", width=10, max_lines=0))

    assert result == []
