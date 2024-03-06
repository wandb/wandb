"""footer tests."""

import re

import numpy as np
import pytest
import wandb

LINE_PREFIX = "wandb: "
RUN_SUMMARY = "Run summary:"
RUN_HISTORY = "Run history:"
FOOTER_END_PREFIX = "Synced "


# wandb: Run summary:
# wandb:        accuracy 0.91145
# wandb:    val_accuracy 0.8948
# wandb: Run history:
# wandb:       accuracy ..
# wandb:          epoch ..
# wandb:
# wandb: Synced 3 W&B file(s), 73 ...


def remove_prefix(text, prefix):
    return text[text.startswith(prefix) and len(prefix) :]


def check_keys(lines, start, end, exp_keys):
    if not exp_keys:
        assert start not in lines
        return
    assert start in lines
    start_idx = lines.index(start)
    end_idx = lines.index(end, start_idx)
    found_lines = lines[start_idx + 1 : end_idx]
    found_keys = [line.split()[0] for line in found_lines if line]
    assert found_keys == exp_keys


@pytest.fixture
def check_output_fn(capsys):
    def check_fn(exp_summary, exp_history):
        captured = capsys.readouterr()
        lines = captured.err.splitlines()
        # for l in captured.err.splitlines():
        #     print("ERR =", l)
        # for l in captured.out.splitlines():
        #     print("OUT =", l)
        lines = [remove_prefix(line, LINE_PREFIX).strip() for line in lines]

        footer_end = next(
            iter([line for line in lines if line.startswith(FOOTER_END_PREFIX)])
        )
        history_end = RUN_SUMMARY if exp_summary else footer_end
        check_keys(lines, RUN_HISTORY, history_end, exp_history)
        check_keys(lines, RUN_SUMMARY, footer_end, exp_summary)

    yield check_fn


def test_footer_private(wandb_init, check_output_fn):
    run = wandb_init()
    run.log(dict(_d=2))
    run.log(dict(_b=2, _d=8))
    run.log(dict(_a=1, _b=2))
    run.log(dict(_a=3))
    run.finish()
    check_output_fn(exp_summary=[], exp_history=[])


def test_footer_normal(wandb_init, check_output_fn):
    run = wandb_init()
    run.log(dict(d=2))
    run.log(dict(b="b", d=8))
    run.log(dict(a=1, b="b"))
    run.log(dict(a=3))
    run.finish()
    check_output_fn(exp_summary=["a", "b", "d", "🚀"], exp_history=["a", "d"])


def test_footer_summary(wandb_init, check_output_fn):
    run = wandb_init()
    run.log(dict(d="d"))
    run.log(dict(b="b", d="d"))
    run.log(dict(a="a", b="b"))
    run.log(dict(a="a"))
    run.finish()
    check_output_fn(exp_summary=["a", "b", "d", "🚀"], exp_history=[])


def test_footer_summary_array(wandb_init, check_output_fn):
    run = wandb_init()
    run.log(dict(d="d"))
    run.log(dict(b="b", d="d"))
    run.log(dict(a="a", b="b", skipthisbecausearray=[1, 2, 3]))
    run.log(dict(a="a"))
    run.finish()
    check_output_fn(exp_summary=["a", "b", "d", "🚀"], exp_history=[])


def test_footer_summary_image(wandb_init, check_output_fn):
    run = wandb_init()
    run.log(dict(d="d"))
    run.log(dict(b="b", d="d"))
    run.log(dict(a="a", b="b"))
    run.log(dict(a="a"))
    run.summary["this-is-ignored"] = wandb.Image(np.random.rand(10, 10))
    run.finish()
    check_output_fn(exp_summary=["a", "b", "d", "🚀"], exp_history=[])


# todo(core): implement sparklines / run history
@pytest.mark.wandb_core_failure(feature="define_metric")
def test_footer_history(wandb_init, check_output_fn):
    run = wandb_init()
    run.define_metric("*", summary="none")
    run.log(dict(d=2))
    run.log(dict(b="b", d=8))
    run.log(dict(a=1, b="b"))
    run.log(dict(a=3))
    run.finish()
    check_output_fn(exp_summary=[], exp_history=["a", "d", "🚀"])


# todo(core): implement job info
@pytest.mark.wandb_core_failure(feature="launch")
def test_footer_job_output(wandb_init, capsys, monkeypatch):
    """Test that footer includes job info when a job is created."""
    monkeypatch.setenv("WANDB_DOCKER", "hello-world")  # Needed to trigger job creation.
    run = wandb_init()
    run.log({"a": 1})
    run.finish()
    captured = capsys.readouterr()
    lines = captured.err.splitlines()
    for line in lines:
        if re.search(
            r"View job at http://localhost:8080/user-\w+-\w+/uncategorized/jobs/[\w=]+/version_details/v0",
            line,
        ):
            break
    else:
        raise AssertionError(f"Job URL not found in footer: {captured.err}")
