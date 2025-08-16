from __future__ import annotations

import re

import wandb


def _run_history_lines(lines: list[str]) -> list[str]:
    """Returns the lines corresponding to the run history footer."""
    try:
        header_idx = lines.index("wandb: Run history:")
        end_idx = lines.index("wandb:", header_idx)
    except ValueError:
        return []

    return lines[header_idx:end_idx]


def _run_summary_lines(lines: list[str]) -> list[str]:
    """Returns the lines corresponding to the run summary footer."""
    try:
        header_idx = lines.index("wandb: Run summary:")
        end_idx = lines.index("wandb:", header_idx)
    except ValueError:
        return []

    return lines[header_idx:end_idx]


def test_online_footer(user, emulated_terminal):
    _ = user

    with wandb.init(project="test-project"):
        emulated_terminal.reset_capsys()

    all_text = "\n".join(emulated_terminal.read_stderr())
    assert "🚀 View run" in all_text
    assert "Find logs at:" in all_text


def test_offline_footer(emulated_terminal):
    with wandb.init(mode="offline"):
        emulated_terminal.reset_capsys()

    all_text = "\n".join(emulated_terminal.read_stderr())
    assert "You can sync this run to the cloud by running:" in all_text
    assert " wandb sync " in all_text
    assert "Find logs at:" in all_text


def test_footer_history(emulated_terminal):
    with wandb.init(mode="offline") as run:
        run.log({"b": 1.4, "a": 1, "_x": 1})
        run.log({"c": -2})

    lines = emulated_terminal.read_stderr()
    assert _run_history_lines(lines) == [
        "wandb: Run history:",
        "wandb: a ▁",
        "wandb: b ▁",
        "wandb: c ▁",
        # _x not shown due to underscore
    ]


def test_footer_history_empty(emulated_terminal):
    with wandb.init(mode="offline"):
        pass

    lines = emulated_terminal.read_stderr()
    assert _run_history_lines(lines) == []


def test_footer_history_downsamples(emulated_terminal):
    with wandb.init(mode="offline") as run:
        for i in range(100):
            run.log({"x": i})

    history = _run_history_lines(emulated_terminal.read_stderr())
    assert len(history) == 2
    history_line = re.fullmatch(r"wandb: x (.+)", history[1])
    assert history_line
    sparkline = history_line.group(1)
    assert len(sparkline) == 40


def test_footer_summary(emulated_terminal):
    with wandb.init(mode="offline") as run:
        run.log({"x": 1, "z": 3, "y": 2})
        run.log({"array_is_skipped": [1, 2, 3]})
        run.log({"z": -5.1, "_private": 0})
        run.log({"nested": {"skipped": 7}})

    lines = emulated_terminal.read_stderr()
    assert _run_summary_lines(lines) == [
        "wandb: Run summary:",
        "wandb: x 1",
        "wandb: y 2",
        "wandb: z -5.1",
    ]


def test_footer_summary_empty(emulated_terminal):
    with wandb.init(mode="offline") as run:
        run.define_metric("*", summary="none")
        run.log({"x": 1})

    lines = emulated_terminal.read_stderr()
    assert _run_summary_lines(lines) == []
